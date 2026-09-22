"""Fund data repository: PostgreSQL persistence for funds and NAV history.

Reads and writes go through the asyncpg engine (app.core.database). All
writes are short transactions; external provider calls never happen inside
them (MVP spec 7.10).
"""

from datetime import date

from sqlalchemy import select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.database import get_async_session
from app.core.logging import logger
from app.integrations.fund_data.models import FundExternalNav, FundExternalProfile, FundExternalRecord
from app.models.fund import Fund, FundNav
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist
from app.utils.clock import utc_now


class FundRepository:
    """Async data access for fund master data and NAV history."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_fund(self, fund_code: str) -> Fund | None:
        """Load one fund master row by code."""
        async with get_async_session() as session:
            result = await session.execute(select(Fund).where(col(Fund.fund_code) == fund_code))
            return result.scalar_one_or_none()

    async def search_funds(self, keyword: str, limit: int = 50) -> list[Fund]:
        """Search local fund master data by code prefix or fuzzy name."""
        keyword_clean = keyword.strip()
        if not keyword_clean:
            return []
        pattern = f"%{keyword_clean}%"
        async with get_async_session() as session:
            statement = (
                select(Fund)
                .where(col(Fund.fund_code).ilike(pattern) | col(Fund.fund_name).ilike(pattern))
                .order_by(col(Fund.fund_code))
                .limit(limit)
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundNav]:
        """Load NAV rows ascending by date between optional bounds."""
        async with get_async_session() as session:
            statement = select(FundNav).where(col(FundNav.fund_code) == fund_code)
            if start_date is not None:
                statement = statement.where(col(FundNav.nav_date) >= start_date)
            if end_date is not None:
                statement = statement.where(col(FundNav.nav_date) <= end_date)
            statement = statement.order_by(col(FundNav.nav_date))
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def get_latest_nav(self, fund_code: str) -> FundNav | None:
        """Load the most recent NAV row for a fund."""
        async with get_async_session() as session:
            statement = (
                select(FundNav)
                .where(col(FundNav.fund_code) == fund_code)
                .order_by(col(FundNav.nav_date).desc())
                .limit(1)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def get_funds(self, fund_codes: list[str]) -> dict[str, Fund]:
        """Load many fund master rows by code, keyed by code."""
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            result = await session.execute(select(Fund).where(col(Fund.fund_code).in_(fund_codes)))
            return {fund.fund_code: fund for fund in result.scalars().all()}

    async def get_latest_navs(self, fund_codes: list[str]) -> dict[str, FundNav]:
        """Load the newest NAV row per fund in a single PostgreSQL DISTINCT ON."""
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            statement = (
                select(FundNav)
                .where(col(FundNav.fund_code).in_(fund_codes))
                .distinct(col(FundNav.fund_code))
                .order_by(col(FundNav.fund_code), col(FundNav.nav_date).desc())
            )
            result = await session.execute(statement)
            return {row.fund_code: row for row in result.scalars().all()}

    async def get_nav_history_map(
        self, fund_codes: list[str], start_date: date | None = None
    ) -> dict[str, list[FundNav]]:
        """Load the NAV series for many funds in one query, keyed by code.

        Each list is ascending by date so the analytics helpers can scan it
        linearly. Funds without rows are omitted.
        """
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            statement = select(FundNav).where(col(FundNav.fund_code).in_(fund_codes))
            if start_date is not None:
                statement = statement.where(col(FundNav.nav_date) >= start_date)
            statement = statement.order_by(col(FundNav.fund_code), col(FundNav.nav_date))
            result = await session.execute(statement)
            series: dict[str, list[FundNav]] = {}
            for row in result.scalars().all():
                series.setdefault(row.fund_code, []).append(row)
            return series

    async def get_hot_fund_codes(self) -> list[str]:
        """Distinct fund codes held or watchlisted by any user (Hot Funds)."""
        position_codes = select(col(PortfolioPosition.fund_code)).distinct()
        watchlist_codes = select(col(Watchlist.fund_code)).distinct()
        async with get_async_session() as session:
            result = await session.execute(union_all(position_codes, watchlist_codes))
            return sorted({row[0] for row in result if row[0]})


class FundWriteRepository:
    """Write-side operations for fund data (upserts)."""

    async def upsert_fund_from_record(self, record: FundExternalProfile | FundExternalRecord) -> None:
        """Insert or update a fund master row from an external record.

        A search/rank record also carries the latest NAV, so that is written as
        a `fund_nav` point too — otherwise a fund that was only ever reached
        through search would list no 净值/涨跌 (spec 3.4 requires both).
        """
        now = utc_now()
        values = {
            "fund_code": record.fund_code,
            "fund_name": record.fund_name,
            "source": "akshare",
            "fetched_at": now,
            "updated_at": now,
        }
        if isinstance(record, FundExternalProfile):
            values.update(
                {
                    "fund_type": record.fund_type,
                    "company": record.company,
                    "manager_name": record.manager_name,
                    "inception_date": record.inception_date,
                    "asset_size": record.asset_size,
                    "benchmark": record.benchmark,
                }
            )
        # Search records carry the public NAV date, which is what the row speaks as of
        as_of = getattr(record, "nav_date", None)
        if as_of is not None:
            values["source_as_of"] = as_of
        async with get_async_session() as session:
            statement = pg_insert(Fund).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[Fund.fund_code],
                set_={key: value for key, value in values.items() if key != "fund_code"},
            )
            await session.execute(statement)

        if isinstance(record, FundExternalRecord) and record.nav_date is not None:
            await self.upsert_navs(
                [
                    FundExternalNav(
                        fund_code=record.fund_code,
                        nav_date=record.nav_date,
                        unit_nav=record.latest_nav,
                        daily_return=record.daily_return,
                    )
                ]
            )

    async def upsert_navs(self, navs: list[FundExternalNav]) -> int:
        """Bulk-upsert NAV rows. Returns the number of rows written."""
        if not navs:
            return 0
        now = utc_now()
        rows = [
            {
                "fund_code": nav.fund_code,
                "nav_date": nav.nav_date,
                "unit_nav": nav.unit_nav,
                "accumulated_nav": nav.accumulated_nav,
                "daily_return": nav.daily_return,
                "source": "akshare",
                "fetched_at": now,
            }
            for nav in navs
        ]
        async with get_async_session() as session:
            statement = pg_insert(FundNav).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_fund_nav_code_date",
                set_={
                    "unit_nav": statement.excluded.unit_nav,
                    "accumulated_nav": statement.excluded.accumulated_nav,
                    "daily_return": statement.excluded.daily_return,
                    "source": statement.excluded.source,
                    "fetched_at": statement.excluded.fetched_at,
                },
            )
            await session.execute(statement)
        logger.debug("fund_navs_upserted", fund_code=navs[0].fund_code, rows=len(rows))
        return len(rows)


fund_repository = FundRepository()
fund_write_repository = FundWriteRepository()
