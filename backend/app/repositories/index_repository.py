"""Index quote repository: PostgreSQL persistence for benchmark closes."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.database import get_async_session
from app.core.logging import logger
from app.integrations.fund_data.models import IndexExternalQuote
from app.models.market import IndexQuote
from app.utils.clock import utc_now

# asyncpg allows at most 32767 bind parameters per statement; 7 columns per row.
_UPSERT_CHUNK_ROWS = 2000


class IndexRepository:
    """Async data access for benchmark index closes."""

    async def get_history(
        self,
        index_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[IndexQuote]:
        """Load closes ascending by date between optional bounds."""
        async with get_async_session() as session:
            statement = select(IndexQuote).where(col(IndexQuote.index_code) == index_code)
            if start_date is not None:
                statement = statement.where(col(IndexQuote.trade_date) >= start_date)
            if end_date is not None:
                statement = statement.where(col(IndexQuote.trade_date) <= end_date)
            statement = statement.order_by(col(IndexQuote.trade_date))
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def get_coverage(self, index_code: str) -> tuple[date, date] | None:
        """Oldest and newest stored close dates, or None when nothing is stored."""
        async with get_async_session() as session:
            statement = select(
                func.min(col(IndexQuote.trade_date)),
                func.max(col(IndexQuote.trade_date)),
            ).where(col(IndexQuote.index_code) == index_code)
            earliest, latest = (await session.execute(statement)).one()
        if earliest is None or latest is None:
            return None
        return earliest, latest

    async def upsert_quotes(self, quotes: list[IndexExternalQuote]) -> int:
        """Bulk-upsert closes in chunks. Returns the number of rows written.

        asyncpg caps one statement at 32767 arguments, and a full index history
        is ~6000 rows of 7 columns, so the values are split rather than sent as
        one insert.
        """
        if not quotes:
            return 0
        now = utc_now()
        written = 0
        async with get_async_session() as session:
            for offset in range(0, len(quotes), _UPSERT_CHUNK_ROWS):
                chunk = quotes[offset : offset + _UPSERT_CHUNK_ROWS]
                rows = [
                    {
                        "index_code": quote.index_code,
                        "trade_date": quote.trade_date,
                        "close": quote.close,
                        "source": "akshare",
                        "fetched_at": now,
                        "created_at": now,
                    }
                    for quote in chunk
                ]
                statement = pg_insert(IndexQuote).values(rows)
                statement = statement.on_conflict_do_update(
                    constraint="uq_index_quote_code_date",
                    set_={
                        "close": statement.excluded.close,
                        "source": statement.excluded.source,
                        "fetched_at": statement.excluded.fetched_at,
                    },
                )
                await session.execute(statement)
                written += len(rows)
        logger.debug("index_quotes_upserted", index_code=quotes[0].index_code, rows=written)
        return written


index_repository = IndexRepository()
