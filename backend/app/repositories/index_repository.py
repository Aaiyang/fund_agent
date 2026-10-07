"""指数行情仓储：基准指数收盘点位在 PostgreSQL 的落库."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.database import get_async_session
from app.core.logging import logger
from app.integrations.fund_data.models import IndexExternalQuote
from app.models.market import IndexQuote
from app.utils.clock import utc_now

# asyncpg 单条语句最多 32767 个绑定参数；这里每行 7 列。
_UPSERT_CHUNK_ROWS = 2000


class IndexRepository:
    """基准指数收盘点位的异步数据访问."""

    async def get_history(
        self,
        index_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[IndexQuote]:
        """按日期升序读取收盘点位，起止日期可选."""
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
        """已存的最早与最晚收盘日期，一条都没存时返回 None."""
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
        """分片批量 upsert 收盘点位，返回写入的行数.

        asyncpg 把单条语句的参数上限卡在 32767，而一只指数的完整历史约 6000 行、
        每行 7 列，所以要把值切开分批写，而不是一条 insert 全发过去。
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
