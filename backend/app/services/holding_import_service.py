"""持仓导入的流程编排：解析 → 复核 → 确认 → 落库.

只有 confirm_import() 会写 portfolio_position。导入带来的写入一律按"覆盖当前
快照"的语义处理，并给每个生效的基金追加一条 IMPORT_ADJUSTMENT 审计流水
（MVP spec 3.7）。截图只以临时文件存在，确认、失败或取消之后就会被删掉。
"""

import asyncio
import io
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from PIL import Image

from app.analytics.settlement import latest_session
from app.core.config import settings
from app.core.database import transaction_scope
from app.core.logging import logger
from app.core.metrics import holding_import_items_total, holding_imports_total, screenshot_parse_duration_seconds
from app.core.task_queue import enqueue
from app.integrations.holdings.base import (
    DraftPositionItem,
    HoldingImportPayload,
    ManualPositionInput,
)
from app.integrations.holdings.manual_provider import ManualImportProvider
from app.integrations.holdings.normalizer import LOW_CONFIDENCE_THRESHOLD, validate_draft_item
from app.integrations.holdings.screenshot_provider import ScreenshotImportProvider
from app.models.holding_import import HoldingImport, HoldingImportItem
from app.repositories.import_repository import import_repository
from app.repositories.job_repository import job_repository
from app.repositories.portfolio_repository import portfolio_repository
from app.schemas.holding_import import ImportCandidate, ImportDetail, ImportItemOut
from app.services.fund_service import fund_service
from app.services.portfolio_service import portfolio_service
from app.workers import SCREENSHOT_IMPORT_TASK
from app.utils.clock import utc_now, business_today
from app.utils.holding_review import holding_review_digest

_ALLOWED_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class ImportStateError(Exception):
    """导入当前状态不允许执行该操作."""


class UploadValidationError(Exception):
    """上传的文件违反数量/大小/类型限制."""


class HoldingImportService:
    """异步的持仓导入编排."""

    # ------------------------------------------------------------------
    # 创建批次
    # ------------------------------------------------------------------

    async def create_manual_import(
        self,
        user_id: int,
        account_id: int,
        positions: list[ManualPositionInput],
    ) -> ImportDetail:
        """同步解析手动录入的各行，存下来等待用户确认."""
        if not positions:
            raise UploadValidationError("no_positions_provided")
        await portfolio_service.ensure_account(user_id, account_id)

        record = await import_repository.create_import(user_id, account_id, "MANUAL", status="UPLOADED")
        draft = await ManualImportProvider().parse(
            HoldingImportPayload(account_id=account_id, manual_positions=positions)
        )
        await import_repository.replace_items(record.id, draft.items)
        await import_repository.update_import(record.id, status="REVIEW_REQUIRED", items_detected=len(draft.items))
        holding_imports_total.labels(import_type="MANUAL", status="REVIEW_REQUIRED").inc()

        refreshed = await import_repository.get_import(user_id, record.id)
        if refreshed is None:
            raise ImportStateError("import_creation_failed")
        detail = await self.get_import_detail(user_id, refreshed.id)
        if detail is None:
            raise ImportStateError("import_detail_unavailable")
        return detail

    async def create_screenshot_import(
        self,
        user_id: int,
        account_id: int | None,
        files: list[UploadFile],
        *,
        chat_session_id: str | None = None,
        defer_processing: bool = False,
    ) -> HoldingImport:
        """校验并保存截图，把解析任务入队交给后台执行.

        立刻返回一个 UPLOADED 状态的批次——真正的解析发生在后台 worker 队列里
        （HTTP 202 模式，spec 7.9）。
        """
        if not files:
            raise UploadValidationError("no_images_provided")
        if len(files) > settings.HOLDING_IMPORT_MAX_IMAGES:
            raise UploadValidationError(f"too_many_images_max_{settings.HOLDING_IMPORT_MAX_IMAGES}")
        if account_id is None:
            if chat_session_id is None:
                raise UploadValidationError("account_required")
        else:
            await portfolio_service.ensure_account(user_id, account_id)

        record = await import_repository.create_import(
            user_id,
            account_id,
            "SCREENSHOT",
            status="UPLOADED",
            image_count=len(files),
            chat_session_id=chat_session_id,
        )
        try:
            paths = await self._save_images(record.id, files)
        except Exception:
            # 上传被拒后不能留下临时图片，也不能留下卡住的批次
            await self._cleanup_images(record.id)
            await import_repository.update_import(record.id, status="PARSE_FAILED", error_message="upload_rejected")
            raise
        if not defer_processing:
            await self.start_screenshot_import(user_id, record.id)
        logger.info("screenshot_attachment_saved", import_id=record.id, deferred=defer_processing, images=len(paths))
        return record

    async def start_screenshot_import(self, user_id: int, import_id: str) -> None:
        """由子图启动 OCR；批次锁保证重复提交或恢复不重复入队."""
        async with transaction_scope():
            record = await import_repository.get_import(user_id, import_id, for_update=True)
            if record is None or record.import_type != "SCREENSHOT":
                raise ImportStateError("import_not_found")
            if record.status != "UPLOADED":
                return
            job = await job_repository.create("SCREENSHOT_IMPORT", subject=record.id)
            await import_repository.update_import(record.id, status="PARSING", started_at=utc_now())
        try:
            await enqueue(SCREENSHOT_IMPORT_TASK, import_id=record.id, user_id=user_id, job_id=job.id)
        except Exception:
            await self.mark_failed(import_id, "screenshot_enqueue_failed")
            raise
        logger.info("screenshot_import_enqueued", import_id=record.id, job_id=job.id)

    # ------------------------------------------------------------------
    # worker 入口
    # ------------------------------------------------------------------

    async def process_screenshot_import(self, import_id: str, user_id: int) -> None:
        """解析截图，把批次推进到 REVIEW_REQUIRED."""
        record = await import_repository.get_import(user_id, import_id)
        if record is None or record.status not in {"UPLOADED", "PARSING"}:
            logger.warning("screenshot_import_unexpected_state", import_id=import_id)
            return

        started = time.monotonic()
        image_paths = await asyncio.to_thread(self._existing_image_paths, import_id)
        try:
            draft = await ScreenshotImportProvider().parse(
                HoldingImportPayload(account_id=record.account_id, image_paths=image_paths)
            )
        except Exception as e:
            await self.mark_failed(import_id, f"ocr_extraction_failed: {e}")
            return

        screenshot_parse_duration_seconds.observe(time.monotonic() - started)

        if not draft.items:
            await self.mark_failed(import_id, draft.error_message or "no_positions_detected")
            return

        async with transaction_scope():
            latest = await import_repository.get_import(user_id, import_id, for_update=True)
            if latest is None or latest.status not in {"UPLOADED", "PARSING"}:
                logger.info("screenshot_result_discarded", import_id=import_id)
                return
            await import_repository.replace_items(import_id, draft.items)
            await import_repository.update_import(
                import_id,
                status="REVIEW_REQUIRED",
                items_detected=len(draft.items),
                image_hashes=draft.image_hashes,
                error_message=draft.error_message,
            )
        for item in draft.items:
            band = "low" if (item.confidence or 0.0) < LOW_CONFIDENCE_THRESHOLD else "ok"
            holding_import_items_total.labels(band=band).inc()
        holding_imports_total.labels(import_type="SCREENSHOT", status="REVIEW_REQUIRED").inc()

    async def mark_failed(self, import_id: str, message: str) -> None:
        """置为失败终态，并清理图片."""
        async with transaction_scope():
            record = await import_repository.get_import(None, import_id, for_update=True)
            if record is not None and record.status in {"APPLIED", "CANCELLED"}:
                return
            import_type = record.import_type if record else "SCREENSHOT"
            await import_repository.update_import(import_id, status="PARSE_FAILED", error_message=message)
        holding_imports_total.labels(import_type=import_type, status="PARSE_FAILED").inc()
        await self._cleanup_images(import_id)
        logger.warning("import_marked_failed", import_id=import_id, message=message[:200])

    # ------------------------------------------------------------------
    # 读取 / 复核
    # ------------------------------------------------------------------

    async def get_import_detail(self, user_id: int, import_id: str) -> ImportDetail | None:
        """导入批次加明细，并为每条补上与当前持仓的对比数据."""
        record = await import_repository.get_import(user_id, import_id)
        if record is None:
            return None

        # 兜底回收：停在 PARSING 超过时限的批次，说明处理它的 worker 已经没了
        if record.status == "PARSING":
            stale = await import_repository.find_stale_parsing()
            if any(batch.id == import_id for batch in stale):
                await self.mark_failed(import_id, f"worker_lost_after_{settings.HOLDING_IMPORT_STALE_MINUTES}m")
                record = (await import_repository.get_import(user_id, import_id)) or record

        items = await import_repository.list_items(import_id)
        item_outs: list[ImportItemOut] = []
        for item in items:
            current = None
            if item.matched_fund_code and record.account_id is not None:
                current = await portfolio_repository.get_position(user_id, record.account_id, item.matched_fund_code)
            item_outs.append(
                self._item_out(
                    item,
                    current.market_value if current else None,
                    current.version if current else None,
                    await self._candidates_for(item),
                )
            )
        return self._detail(record, item_outs)

    async def _candidates_for(self, item: HoldingImportItem) -> list[ImportCandidate]:
        """解析时没能定下名称的那条，给出它可能对应的候选基金.

        截图里名称被截断的那一行，通常对应同一只基金的几个份额类别；把候选列出来，
        用户点一下就修正了，不用他自己去查、再手动敲进 6 位代码。
        """
        if item.matched_fund_code or not item.raw_fund_name:
            return []
        return [
            ImportCandidate(fund_code=match.fund_code, fund_name=match.fund_name, score=match.score)
            for match in await fund_service.match_fund_names(item.raw_fund_name)
        ]

    async def update_item(
        self,
        user_id: int,
        import_id: str,
        item_id: int,
        user_action: str | None = None,
        **fields: float | str | date | bool | None,
    ) -> ImportItemOut:
        """用户对单条明细的修改与处置；改过的值会重新走一遍校验."""
        async with transaction_scope():
            return await self._update_item_locked(user_id, import_id, item_id, user_action=user_action, **fields)

    async def _update_item_locked(
        self,
        user_id: int,
        import_id: str,
        item_id: int,
        user_action: str | None,
        **fields: float | str | date | bool | None,
    ) -> ImportItemOut:
        """草稿编辑和确认共用批次行锁，防止用户确认时草稿被并发改写."""
        record = await import_repository.get_import(user_id, import_id, for_update=True)
        if record is None:
            raise ImportStateError("import_not_found")
        if record.status != "REVIEW_REQUIRED":
            raise ImportStateError(f"import_not_editable_in_state_{record.status}")

        item = await import_repository.get_item(import_id, item_id)
        if item is None:
            raise ImportStateError("item_not_found")

        if "fund_code" in fields and fields["fund_code"]:
            fund, confidence = await fund_service.resolve_fund(None, str(fields["fund_code"]))
            item.matched_fund_code = fund.fund_code if fund else str(fields["fund_code"])
            item.matched_fund_name = fund.fund_name if fund else None
            item.confidence = confidence if fund else item.confidence

        for key in ("market_value", "shares", "cost_amount", "average_cost_nav", "profit_loss", "profit_loss_rate"):
            if key in fields:
                setattr(item, key, fields[key])
        if user_action is not None:
            item.user_action = user_action

        draft_item = DraftPositionItem(
            raw_fund_name=item.raw_fund_name,
            matched_fund_code=item.matched_fund_code,
            matched_fund_name=item.matched_fund_name,
            market_value=item.market_value,
            shares=item.shares,
            cost_amount=item.cost_amount,
            average_cost_nav=item.average_cost_nav,
            profit_loss=item.profit_loss,
            profit_loss_rate=item.profit_loss_rate,
            confidence=item.confidence or 0.5,
        )
        validated = validate_draft_item(draft_item)
        item.validation_status = validated.validation_status
        item.validation_issues = validated.validation_issues
        await import_repository.update_item(item)
        # 带上详情视图里那组同样的对比字段；少了它们，复核页每改一次就会
        # 丢掉"当前持仓 / 版本"。
        current = None
        if item.matched_fund_code and record.account_id is not None:
            current = await portfolio_repository.get_position(user_id, record.account_id, item.matched_fund_code)
        return self._item_out(
            item,
            current.market_value if current else None,
            current.version if current else None,
        )

    # ------------------------------------------------------------------
    # 确认 / 取消
    # ------------------------------------------------------------------

    async def confirm_import(
        self, user_id: int, import_id: str, *, expected_review_digest: str | None = None
    ) -> dict[str, int]:
        """把已确认的明细落到持仓上——这是持仓唯一的写入入口.

        语义按 spec 3.7：按基金覆盖当前快照；不合成 BUY/SELL 流水；
        每个生效的基金补一条 IMPORT_ADJUSTMENT 审计流水。
        """
        async with transaction_scope():
            record = await import_repository.get_import(user_id, import_id, for_update=True)
            if record is None:
                raise ImportStateError("import_not_found")
            if record.status == "APPLIED":
                result = {"applied": record.items_confirmed, "skipped": record.items_detected - record.items_confirmed}
                newly_applied = False
            elif record.status != "REVIEW_REQUIRED":
                raise ImportStateError(f"import_not_confirmable_in_state_{record.status}")
            else:
                if expected_review_digest is not None:
                    detail = await self.get_import_detail(user_id, import_id)
                    if detail is None or holding_review_digest(detail) != expected_review_digest:
                        raise ImportStateError("import_review_changed")
                result = await self._apply_confirmed_import(user_id, import_id, record)
                newly_applied = True
        if newly_applied:
            holding_imports_total.labels(import_type=record.import_type, status="APPLIED").inc()
        await self._cleanup_images(import_id)
        logger.info("import_confirmed", import_id=import_id, applied=result["applied"], skipped=result["skipped"])
        return result

    async def _apply_confirmed_import(self, user_id: int, import_id: str, record: HoldingImport) -> dict[str, int]:
        """由持有批次行锁的事务调用，所有持仓、流水与状态要么一起提交，要么一起回滚."""
        if record.account_id is None:
            raise ImportStateError("import_account_required")
        await portfolio_service.ensure_account(user_id, record.account_id, for_update=True)
        items = await import_repository.list_items(import_id)
        applied = skipped = 0
        for item in items:
            action = item.user_action or ("UPDATE" if item.validation_status != "error" else "SKIP")
            if action == "SKIP" or not item.matched_fund_code:
                skipped += 1
                continue

            fields = {
                key: getattr(item, key)
                for key in ("market_value", "shares", "cost_amount", "average_cost_nav", "profit_loss")
                if getattr(item, key) is not None
            }
            # 这一天不由用户来挑：已经持有的基金沿用原先设好的日期
            # （重新导入一份快照不能把他的持有天数清零），第一次见到的
            # 基金则从最近一个交易日起算——钱本来就已经在场内了，
            # 所以该从应用能看到它的那天算起，而不是从他
            # 执行导入的那天算起。
            current = await portfolio_repository.get_position(user_id, record.account_id, item.matched_fund_code)
            held_since = current.purchase_date if current is not None else None
            # 导入覆盖是用户的明确意图——跳过乐观锁版本校验
            # （expected_version=None），但存进去的版本号照样自增。
            position = await portfolio_repository.upsert_position(
                user_id,
                record.account_id,
                item.matched_fund_code,
                expected_version=None,
                allow_unversioned_update=True,
                purchase_date=held_since or latest_session(business_today()),
                **fields,
            )
            if position is None:
                skipped += 1
                continue
            await portfolio_repository.add_transaction(
                user_id=user_id,
                account_id=record.account_id,
                fund_code=item.matched_fund_code,
                transaction_type="IMPORT_ADJUSTMENT",
                trade_date=business_today(),
                shares=position.shares,
                nav=position.average_cost_nav,
                amount=position.market_value,
                source=f"{record.import_type.lower()}_import",
                external_transaction_id=import_id,
            )
            applied += 1

        await import_repository.update_import(
            import_id,
            status="APPLIED",
            items_confirmed=applied,
            confirmed_at=utc_now(),
            applied_at=utc_now(),
        )
        await portfolio_repository.touch_account_imported(user_id, record.account_id)
        return {"applied": applied, "skipped": skipped}

    async def delete_import(self, user_id: int, import_id: str) -> bool:
        """取消还没落库的导入，并删掉它的临时图片."""
        async with transaction_scope():
            record = await import_repository.get_import(user_id, import_id, for_update=True)
            if record is None:
                return False
            if record.status == "APPLIED":
                raise ImportStateError("applied_import_cannot_be_deleted")
            await import_repository.update_import(import_id, status="CANCELLED")
            await import_repository.delete_items(import_id)
        holding_imports_total.labels(import_type=record.import_type, status="CANCELLED").inc()
        await self._cleanup_images(import_id)
        logger.info("import_cancelled", import_id=import_id)
        return True

    async def list_history(self, user_id: int, limit: int = 50) -> list[ImportDetail]:
        """导入批次的历史列表，不带每条明细的数据."""
        records = await import_repository.list_history(user_id, limit)
        return [self._detail(record, []) for record in records]

    # ------------------------------------------------------------------
    # 图片处理
    # ------------------------------------------------------------------

    async def _save_images(self, import_id: str, files: list[UploadFile]) -> list[str]:
        """校验上传的图片，并落到临时目录."""
        max_bytes = settings.HOLDING_IMPORT_MAX_IMAGE_MB * 1024 * 1024
        temp_dir = Path(settings.HOLDING_IMPORT_TEMP_DIR)
        saved: list[str] = []

        for index, upload in enumerate(files):
            # 超限文件不能整份进内存：先按 Starlette 解析出的分片大小早拒，
            # 再只读 max_bytes+1 字节做兜底判定
            declared = getattr(upload, "size", None)
            if declared is not None and declared > max_bytes:
                raise UploadValidationError(f"image_{index}_exceeds_{settings.HOLDING_IMPORT_MAX_IMAGE_MB}mb")
            content = await upload.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise UploadValidationError(f"image_{index}_exceeds_{settings.HOLDING_IMPORT_MAX_IMAGE_MB}mb")
            try:
                with Image.open(io.BytesIO(content)) as img:
                    fmt = (img.format or "").upper()
            except Exception as e:
                raise UploadValidationError(f"image_{index}_not_valid") from e
            ext = _ALLOWED_FORMATS.get(fmt)
            if ext is None:
                raise UploadValidationError(f"image_{index}_unsupported_format_{fmt}")

            path = temp_dir / f"{import_id}_{index}{ext}"
            await asyncio.to_thread(path.write_bytes, content)
            saved.append(str(path))
        return saved

    def _existing_image_paths(self, import_id: str) -> list[str]:
        """按顺序给出该导入在临时目录里的图片路径."""
        temp_dir = Path(settings.HOLDING_IMPORT_TEMP_DIR)
        if not temp_dir.exists():
            return []
        return [str(path) for path in sorted(temp_dir.glob(f"{import_id}_*"))]

    async def _cleanup_images(self, import_id: str) -> None:
        """删掉该导入的临时图片（隐私：原图绝不做持久化）."""

        def _remove() -> int:
            temp_dir = Path(settings.HOLDING_IMPORT_TEMP_DIR)
            removed = 0
            for path in temp_dir.glob(f"{import_id}_*"):
                path.unlink(missing_ok=True)
                removed += 1
            return removed

        try:
            removed = await asyncio.to_thread(_remove)
            if removed:
                logger.info("import_images_deleted", import_id=import_id, count=removed)
        except Exception as e:
            logger.warning("import_image_cleanup_failed", import_id=import_id, error=str(e))

    # ------------------------------------------------------------------
    # 输出映射
    # ------------------------------------------------------------------

    @staticmethod
    def _item_out(
        item: HoldingImportItem,
        current_market_value: float | None,
        current_version: int | None,
        candidates: Sequence[ImportCandidate] = (),
    ) -> ImportItemOut:
        """把明细行映射成输出 schema，一并带上对比字段."""
        raw_issues = item.validation_issues
        issues = [str(issue) for issue in raw_issues] if isinstance(raw_issues, list) else []
        return ImportItemOut(
            id=item.id or 0,
            raw_fund_name=item.raw_fund_name,
            matched_fund_code=item.matched_fund_code,
            matched_fund_name=item.matched_fund_name,
            market_value=item.market_value,
            shares=item.shares,
            cost_amount=item.cost_amount,
            average_cost_nav=item.average_cost_nav,
            profit_loss=item.profit_loss,
            profit_loss_rate=item.profit_loss_rate,
            confidence=item.confidence,
            validation_status=item.validation_status,
            validation_issues=issues,
            user_action=item.user_action,
            current_market_value=current_market_value,
            current_version=current_version,
            candidates=list(candidates),
        )

    @staticmethod
    def _detail(record: HoldingImport, items: list[ImportItemOut]) -> ImportDetail:
        """把导入批次行映射成输出 schema."""
        return ImportDetail(
            id=record.id,
            account_id=record.account_id,
            import_type=record.import_type,
            status=record.status,
            image_count=record.image_count,
            items_detected=record.items_detected,
            items_confirmed=record.items_confirmed,
            error_message=record.error_message,
            started_at=record.started_at,
            confirmed_at=record.confirmed_at,
            applied_at=record.applied_at,
            created_at=record.created_at,
            items=items,
        )


holding_import_service = HoldingImportService()
