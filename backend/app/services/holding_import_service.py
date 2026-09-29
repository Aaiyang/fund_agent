"""Holding import orchestration: parse → review → confirm → apply.

The only path that writes to portfolio_position is confirm_import(). All
import writes follow "overwrite current snapshot" semantics and append an
IMPORT_ADJUSTMENT audit transaction (MVP spec 3.7). Screenshot images live
only as temporary files and are deleted after confirm/fail/cancel.
"""

import asyncio
import io
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from PIL import Image

from app.core.config import settings
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

_ALLOWED_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class ImportStateError(Exception):
    """Operation not allowed in the import's current state."""


class UploadValidationError(Exception):
    """Uploaded files violate count/size/type limits."""


class HoldingImportService:
    """Async holdings import orchestration."""

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    async def create_manual_import(
        self,
        user_id: int,
        account_id: int,
        source_app: str | None,
        positions: list[ManualPositionInput],
    ) -> ImportDetail:
        """Parse manual rows synchronously and park them for confirmation."""
        if not positions:
            raise UploadValidationError("no_positions_provided")
        await portfolio_service.ensure_account(user_id, account_id)

        record = await import_repository.create_import(user_id, account_id, "MANUAL", source_app, status="UPLOADED")
        draft = await ManualImportProvider().parse(
            HoldingImportPayload(account_id=account_id, source_app=source_app, manual_positions=positions)
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
        account_id: int,
        source_app: str | None,
        files: list[UploadFile],
    ) -> HoldingImport:
        """Validate and store screenshots, enqueue async parsing.

        Returns immediately with an UPLOADED batch — parsing happens in the
        worker queue (HTTP 202 pattern, spec 7.9).
        """
        if not files:
            raise UploadValidationError("no_images_provided")
        if len(files) > settings.HOLDING_IMPORT_MAX_IMAGES:
            raise UploadValidationError(f"too_many_images_max_{settings.HOLDING_IMPORT_MAX_IMAGES}")
        await portfolio_service.ensure_account(user_id, account_id)

        record = await import_repository.create_import(
            user_id, account_id, "SCREENSHOT", source_app, status="UPLOADED", image_count=len(files)
        )
        try:
            paths = await self._save_images(record.id, files)
        except Exception:
            # A rejected upload must not leave temp images or a stuck batch behind
            await self._cleanup_images(record.id)
            await import_repository.update_import(record.id, status="PARSE_FAILED", error_message="upload_rejected")
            raise
        await import_repository.update_import(record.id, status="PARSING")
        job = await job_repository.create("SCREENSHOT_IMPORT", subject=record.id)

        await enqueue(SCREENSHOT_IMPORT_TASK, import_id=record.id, user_id=user_id, job_id=job.id)
        logger.info("screenshot_import_enqueued", import_id=record.id, job_id=job.id, images=len(paths))
        return record

    # ------------------------------------------------------------------
    # Worker entry
    # ------------------------------------------------------------------

    async def process_screenshot_import(self, import_id: str, user_id: int) -> None:
        """Parse screenshots and move the batch to REVIEW_REQUIRED."""
        record = await import_repository.get_import(user_id, import_id)
        if record is None or record.status not in {"UPLOADED", "PARSING"}:
            logger.warning("screenshot_import_unexpected_state", import_id=import_id)
            return

        started = time.monotonic()
        image_paths = await asyncio.to_thread(self._existing_image_paths, import_id)
        try:
            draft = await ScreenshotImportProvider().parse(
                HoldingImportPayload(
                    account_id=record.account_id, source_app=record.source_app, image_paths=image_paths
                )
            )
        except Exception as e:
            await self.mark_failed(import_id, f"ocr_extraction_failed: {e}")
            return

        screenshot_parse_duration_seconds.observe(time.monotonic() - started)

        if not draft.items:
            await self.mark_failed(import_id, draft.error_message or "no_positions_detected")
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
        """Terminal failure state + image cleanup."""
        record = await import_repository.get_import(None, import_id)  # internal path
        import_type = record.import_type if record else "SCREENSHOT"
        await import_repository.update_import(import_id, status="PARSE_FAILED", error_message=message)
        holding_imports_total.labels(import_type=import_type, status="PARSE_FAILED").inc()
        await self._cleanup_images(import_id)
        logger.warning("import_marked_failed", import_id=import_id, message=message[:200])

    # ------------------------------------------------------------------
    # Read / review
    # ------------------------------------------------------------------

    async def get_import_detail(self, user_id: int, import_id: str) -> ImportDetail | None:
        """Import + items enriched with current-position diff data."""
        record = await import_repository.get_import(user_id, import_id)
        if record is None:
            return None

        # Reaper: batches stuck in PARSING past the budget are dead workers
        if record.status == "PARSING":
            stale = await import_repository.find_stale_parsing()
            if any(batch.id == import_id for batch in stale):
                await self.mark_failed(import_id, f"worker_lost_after_{settings.HOLDING_IMPORT_STALE_MINUTES}m")
                record = (await import_repository.get_import(user_id, import_id)) or record

        items = await import_repository.list_items(import_id)
        item_outs: list[ImportItemOut] = []
        for item in items:
            current = None
            if item.matched_fund_code:
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
        """The funds a name the parse could not settle on might still be.

        A screenshot row whose name is truncated is usually several share
        classes of one fund; listing them turns the fix into one tap instead of
        making him look up and type a 6-digit code.
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
        """User edit/decision on one item; corrections are re-validated."""
        record = await import_repository.get_import(user_id, import_id)
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
        # The purchase date is what the confirmation will write, so it is
        # corrected here rather than invented later.
        if "purchase_date" in fields:
            value = fields["purchase_date"]
            item.purchase_date = value if isinstance(value, date) else None
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
            purchase_date=item.purchase_date,
            confidence=item.confidence or 0.5,
        )
        validated = validate_draft_item(draft_item)
        item.validation_status = validated.validation_status
        item.validation_issues = validated.validation_issues
        await import_repository.update_item(item)
        # Carry the same diff fields the detail view shows; without them the
        # review page loses "当前持仓 / 版本" after every edit.
        current = None
        if item.matched_fund_code:
            current = await portfolio_repository.get_position(user_id, record.account_id, item.matched_fund_code)
        return self._item_out(
            item,
            current.market_value if current else None,
            current.version if current else None,
        )

    # ------------------------------------------------------------------
    # Confirm / cancel
    # ------------------------------------------------------------------

    async def confirm_import(self, user_id: int, import_id: str) -> dict[str, int]:
        """Apply confirmed items to positions — the only holdings write path.

        Semantics per spec 3.7: overwrite current snapshot per fund; no BUY/
        SELL synthesis; one IMPORT_ADJUSTMENT audit row per applied fund.
        """
        record = await import_repository.get_import(user_id, import_id)
        if record is None:
            raise ImportStateError("import_not_found")
        if record.status != "REVIEW_REQUIRED":
            raise ImportStateError(f"import_not_confirmable_in_state_{record.status}")

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
            # The review page owns the purchase date: it arrives prefilled with
            # the import day before the cutoff and the user moves it when he
            # knows better. An existing row keeps the date it was set to —
            # re-importing a snapshot must not reset someone's holding age.
            current = await portfolio_repository.get_position(user_id, record.account_id, item.matched_fund_code)
            keep = current is not None and current.purchase_date is not None
            # Import overwrite is explicit user intent — bypass version check
            # (expected_version=None) but still bump the stored version.
            position = await portfolio_repository.upsert_position(
                user_id,
                record.account_id,
                item.matched_fund_code,
                expected_version=None,
                purchase_date=None if keep else item.purchase_date,
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
        holding_imports_total.labels(import_type=record.import_type, status="APPLIED").inc()
        await self._cleanup_images(import_id)
        logger.info("import_confirmed", import_id=import_id, applied=applied, skipped=skipped)
        return {"applied": applied, "skipped": skipped}

    async def delete_import(self, user_id: int, import_id: str) -> bool:
        """Cancel a non-applied import and delete its temp images."""
        record = await import_repository.get_import(user_id, import_id)
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
        """Import batch history without item payloads."""
        records = await import_repository.list_history(user_id, limit)
        return [self._detail(record, []) for record in records]

    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------

    async def _save_images(self, import_id: str, files: list[UploadFile]) -> list[str]:
        """Validate and persist uploaded images to the temp directory."""
        max_bytes = settings.HOLDING_IMPORT_MAX_IMAGE_MB * 1024 * 1024
        temp_dir = Path(settings.HOLDING_IMPORT_TEMP_DIR)
        saved: list[str] = []

        for index, upload in enumerate(files):
            content = await upload.read()
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
        """Temp image paths for an import, ordered."""
        temp_dir = Path(settings.HOLDING_IMPORT_TEMP_DIR)
        if not temp_dir.exists():
            return []
        return [str(path) for path in sorted(temp_dir.glob(f"{import_id}_*"))]

    async def _cleanup_images(self, import_id: str) -> None:
        """Delete temp images for an import (privacy: originals never persist)."""

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
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _item_out(
        item: HoldingImportItem,
        current_market_value: float | None,
        current_version: int | None,
        candidates: Sequence[ImportCandidate] = (),
    ) -> ImportItemOut:
        """Map an item row to its output schema with diff fields."""
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
            purchase_date=item.purchase_date,
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
        """Map an import row to its output schema."""
        return ImportDetail(
            id=record.id,
            account_id=record.account_id,
            import_type=record.import_type,
            source_app=record.source_app,
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
