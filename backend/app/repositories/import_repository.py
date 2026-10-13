"""持仓导入仓储：导入批次与待确认条目."""

from datetime import datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlmodel import col

from app.core.config import settings
from app.core.database import get_async_session
from app.integrations.holdings.base import DraftPositionItem
from app.models.holding_import import HoldingImport, HoldingImportItem
from app.utils.clock import utc_now


class ImportRepository:
    """导入批次与批次条目的异步数据访问."""

    async def create_import(
        self,
        user_id: int,
        account_id: int | None,
        import_type: str,
        status: str,
        image_count: int = 0,
        image_hashes: list[str] | None = None,
        chat_session_id: str | None = None,
    ) -> HoldingImport:
        """新建一条导入批次记录."""
        async with get_async_session() as session:
            record = HoldingImport(
                user_id=user_id,
                account_id=account_id,
                import_type=import_type,
                status=status,
                image_count=image_count,
                image_hashes=image_hashes or [],
                chat_session_id=chat_session_id,
                started_at=utc_now(),
            )
            session.add(record)
            await session.flush()
            return record

    async def get_import(
        self, user_id: int | None, import_id: str, *, for_update: bool = False
    ) -> HoldingImport | None:
        """读取一个导入批次；user_id 传 None 是给系统内部用的."""
        statement = select(HoldingImport).where(col(HoldingImport.id) == import_id)
        if user_id is not None:
            statement = statement.where(col(HoldingImport.user_id) == user_id)
        if for_update:
            statement = statement.with_for_update()
        async with get_async_session() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def update_import(
        self,
        import_id: str,
        status: str | None = None,
        error_message: str | None = None,
        items_detected: int | None = None,
        items_confirmed: int | None = None,
        image_hashes: list[str] | None = None,
        confirmed_at: datetime | None = None,
        applied_at: datetime | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """修改导入批次的可变字段（状态流转、计数）."""
        async with get_async_session() as session:
            record = (
                await session.execute(select(HoldingImport).where(col(HoldingImport.id) == import_id))
            ).scalar_one_or_none()
            if record is None:
                return
            if status is not None:
                record.status = status
            if error_message is not None:
                record.error_message = error_message[:500]
            if items_detected is not None:
                record.items_detected = items_detected
            if items_confirmed is not None:
                record.items_confirmed = items_confirmed
            if image_hashes is not None:
                record.image_hashes = image_hashes
            if confirmed_at is not None:
                record.confirmed_at = confirmed_at
            if applied_at is not None:
                record.applied_at = applied_at
            if started_at is not None:
                record.started_at = started_at
            session.add(record)

    async def list_history(self, user_id: int, limit: int = 50) -> list[HoldingImport]:
        """按时间倒序列出该用户的导入批次."""
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImport)
                .where(col(HoldingImport.user_id) == user_id)
                .order_by(col(HoldingImport.created_at).desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def replace_items(self, import_id: str, items: list[DraftPositionItem]) -> None:
        """用新的草稿整体替换该批次的待确认条目."""
        async with get_async_session() as session:
            await session.execute(sa_delete(HoldingImportItem).where(col(HoldingImportItem.import_id) == import_id))
            for item in items:
                session.add(
                    HoldingImportItem(
                        import_id=import_id,
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
                        validation_issues=item.validation_issues,
                    )
                )

    async def list_items(self, import_id: str) -> list[HoldingImportItem]:
        """按创建顺序列出该批次的待确认条目."""
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImportItem)
                .where(col(HoldingImportItem.import_id) == import_id)
                .order_by(col(HoldingImportItem.id))
            )
            return list(result.scalars().all())

    async def get_item(self, import_id: str, item_id: int) -> HoldingImportItem | None:
        """读取该批次下的一条条目."""
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImportItem).where(
                    col(HoldingImportItem.id) == item_id, col(HoldingImportItem.import_id) == import_id
                )
            )
            return result.scalar_one_or_none()

    async def update_item(self, item: HoldingImportItem) -> None:
        """保存用户对条目的修改与处置."""
        async with get_async_session() as session:
            session.add(item)

    async def delete_items(self, import_id: str) -> None:
        """删除该批次下的全部条目."""
        async with get_async_session() as session:
            await session.execute(sa_delete(HoldingImportItem).where(col(HoldingImportItem.import_id) == import_id))

    async def find_stale_parsing(self) -> list[HoldingImport]:
        """找出卡在 PARSING 且超过陈旧时限的批次（worker 已经不在了）."""
        cutoff = utc_now() - timedelta(minutes=settings.HOLDING_IMPORT_STALE_MINUTES)
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImport).where(
                    col(HoldingImport.status) == "PARSING", col(HoldingImport.started_at) < cutoff
                )
            )
            return list(result.scalars().all())


import_repository = ImportRepository()
