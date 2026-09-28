"""Holding import repository: batches and pending items."""

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
    """Async data access for holding import batches and items."""

    async def create_import(
        self,
        user_id: int,
        account_id: int,
        import_type: str,
        source_app: str | None,
        status: str,
        image_count: int = 0,
        image_hashes: list[str] | None = None,
    ) -> HoldingImport:
        """Create an import batch record."""
        async with get_async_session() as session:
            record = HoldingImport(
                user_id=user_id,
                account_id=account_id,
                import_type=import_type,
                source_app=source_app,
                status=status,
                image_count=image_count,
                image_hashes=image_hashes or [],
                started_at=utc_now(),
            )
            session.add(record)
            await session.flush()
            return record

    async def get_import(self, user_id: int | None, import_id: str) -> HoldingImport | None:
        """Load one import batch; pass user_id=None for system-internal use."""
        statement = select(HoldingImport).where(col(HoldingImport.id) == import_id)
        if user_id is not None:
            statement = statement.where(col(HoldingImport.user_id) == user_id)
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
    ) -> None:
        """Patch mutable import fields (status transitions, counters)."""
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
            session.add(record)

    async def list_history(self, user_id: int, limit: int = 50) -> list[HoldingImport]:
        """List the user's import batches, newest first."""
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImport)
                .where(col(HoldingImport.user_id) == user_id)
                .order_by(col(HoldingImport.created_at).desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def replace_items(self, import_id: str, items: list[DraftPositionItem]) -> None:
        """Replace all pending items of an import with a new draft."""
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
                        purchase_date=item.purchase_date,
                        confidence=item.confidence,
                        validation_status=item.validation_status,
                        validation_issues=item.validation_issues,
                    )
                )

    async def list_items(self, import_id: str) -> list[HoldingImportItem]:
        """List pending items of an import in creation order."""
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImportItem)
                .where(col(HoldingImportItem.import_id) == import_id)
                .order_by(col(HoldingImportItem.id))
            )
            return list(result.scalars().all())

    async def get_item(self, import_id: str, item_id: int) -> HoldingImportItem | None:
        """Load one item of an import."""
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImportItem).where(
                    col(HoldingImportItem.id) == item_id, col(HoldingImportItem.import_id) == import_id
                )
            )
            return result.scalar_one_or_none()

    async def update_item(self, item: HoldingImportItem) -> None:
        """Persist user edits / action on an item."""
        async with get_async_session() as session:
            session.add(item)

    async def delete_items(self, import_id: str) -> None:
        """Remove all items of an import."""
        async with get_async_session() as session:
            await session.execute(sa_delete(HoldingImportItem).where(col(HoldingImportItem.import_id) == import_id))

    async def find_stale_parsing(self) -> list[HoldingImport]:
        """Imports stuck in PARSING beyond the staleness budget (worker lost)."""
        cutoff = utc_now() - timedelta(minutes=settings.HOLDING_IMPORT_STALE_MINUTES)
        async with get_async_session() as session:
            result = await session.execute(
                select(HoldingImport).where(
                    col(HoldingImport.status) == "PARSING", col(HoldingImport.started_at) < cutoff
                )
            )
            return list(result.scalars().all())


import_repository = ImportRepository()
