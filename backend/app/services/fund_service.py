"""Fund domain service: search, detail, NAV history, performance, resolve.

All fund facts come from FundService — other services, the API layer and the
future Agent tools never touch fund data providers directly (spec 14.1).
Online reads prefer PostgreSQL, with Redis as a hot cache; external sync is
enqueued or inlined only when local data is missing or stale (spec 5.6).
"""

import asyncio
from datetime import date

from sqlalchemy import exists as sa_exists
from sqlalchemy import select
from sqlmodel import col

from app.analytics import max_drawdown, period_return, range_return, annualized_volatility
from app.analytics.returns import NavPoint
from app.core.cache import cache_key, cache_service
from app.core.config import settings
from app.core.database import get_async_session
from app.core.logging import logger
from app.integrations.fund_data.akshare_client import AKSHARE_AVAILABLE
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.models.fund import Fund, FundNav
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist
from app.repositories.fund_repository import fund_repository, fund_write_repository
from app.schemas.fund import (
    FundDetailResponse,
    FundNavHistoryResponse,
    FundNavPoint,
    FundPerformance,
    FundSearchItem,
)
from app.services.fund_sync_service import fund_sync_service

_LATEST_NAV_CACHE_TTL_SECONDS = 300


class FundService:
    """Async fund data service shared by API, imports and future Agent tools."""

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, keyword: str, user_id: int) -> list[FundSearchItem]:
        """Search funds: local database first, external provider on miss.

        Args:
            keyword: Code, full name, abbreviation or fuzzy fragment.
            user_id: Caller id for is_watchlisted / is_held flags.

        Returns:
            Up to 50 fund search items.
        """
        keyword_clean = keyword.strip()
        if not keyword_clean:
            return []

        cache_hit = await cache_service.get(cache_key("fund_search", str(user_id), keyword_clean))
        if cache_hit:
            return self._decode_items(cache_hit)

        local_funds = await fund_repository.search_funds(keyword_clean)
        if not local_funds and AKSHARE_AVAILABLE:
            external = await akshare_fund_provider.search_funds(keyword_clean)
            for record in external[:50]:
                await fund_write_repository.upsert_fund_from_record(record)
            local_funds = await fund_repository.search_funds(keyword_clean)

        items: list[FundSearchItem] = []
        for fund in local_funds[:50]:
            latest = await self._latest_nav_cached(fund.fund_code)
            is_watchlisted, is_held = await self._user_flags(fund.fund_code, user_id)
            items.append(
                FundSearchItem(
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    fund_type=fund.fund_type,
                    latest_nav=latest.unit_nav if latest else None,
                    nav_date=latest.nav_date if latest else None,
                    daily_return=latest.daily_return if latest else None,
                    is_watchlisted=is_watchlisted,
                    is_held=is_held,
                )
            )

        await cache_service.set(
            cache_key("fund_search", str(user_id), keyword_clean),
            self._encode_items(items),
            ttl=_LATEST_NAV_CACHE_TTL_SECONDS,
        )
        return items

    # ------------------------------------------------------------------
    # Detail / NAV / performance
    # ------------------------------------------------------------------

    async def get_detail(self, fund_code: str, user_id: int) -> FundDetailResponse | None:
        """Return the fund overview; syncs data on first sight of a fund."""
        await self.ensure_fund_data(fund_code)
        fund = await fund_repository.get_fund(fund_code)
        if fund is None:
            return None

        latest = await self._latest_nav_cached(fund_code)
        history = await fund_repository.get_nav_history(fund_code)
        points = self._to_points(history)
        is_watchlisted, is_held = await self._user_flags(fund_code, user_id)

        end = latest.nav_date if latest else date.today()
        return FundDetailResponse(
            fund_code=fund.fund_code,
            fund_name=fund.fund_name,
            fund_type=fund.fund_type,
            company=fund.company,
            manager_name=fund.manager_name,
            inception_date=fund.inception_date,
            latest_nav=latest.unit_nav if latest else None,
            accumulated_nav=latest.accumulated_nav if latest else None,
            nav_date=latest.nav_date if latest else None,
            daily_return=latest.daily_return if latest else None,
            performance=self._compute_performance(points, end),
            is_watchlisted=is_watchlisted,
            is_held=is_held,
        )

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FundNavHistoryResponse:
        """Return the stored NAV series for charting (no live pass-through)."""
        await self.ensure_fund_data(fund_code)
        history = await fund_repository.get_nav_history(fund_code, start_date, end_date)
        return FundNavHistoryResponse(
            fund_code=fund_code,
            points=[
                FundNavPoint(
                    nav_date=row.nav_date,
                    unit_nav=row.unit_nav,
                    accumulated_nav=row.accumulated_nav,
                    daily_return=row.daily_return,
                )
                for row in history
            ],
        )

    def _compute_performance(self, points: list[NavPoint], end: date) -> FundPerformance:
        """Compute deterministic period metrics from a NAV series."""
        if not points:
            return FundPerformance()
        earliest = points[0].date
        return FundPerformance(
            return_1m=period_return(points, end, 1),
            return_3m=period_return(points, end, 3),
            return_6m=period_return(points, end, 6),
            return_1y=period_return(points, end, 12),
            return_3y=period_return(points, end, 36),
            return_since_inception=range_return(points, earliest, end),
            max_drawdown=max_drawdown(points),
            annualized_volatility=annualized_volatility(points),
        )

    # ------------------------------------------------------------------
    # Fund resolution (used by holdings imports)
    # ------------------------------------------------------------------

    async def resolve_fund(self, raw_name: str | None, raw_code: str | None) -> tuple[Fund | None, float]:
        """Match raw extracted name/code to a standard fund entity.

        Returns:
            (fund, confidence) — fund is None when unresolvable or ambiguous.
        """
        code_clean = (raw_code or "").strip()
        if code_clean.isdigit() and len(code_clean) == 6:
            fund = await self._get_fund_ensuring_data(code_clean)
            if fund is not None:
                return fund, 0.95
            return None, 0.0

        name_clean = (raw_name or "").strip()
        if not name_clean:
            return None, 0.0

        exact = await fund_repository.search_funds(name_clean, limit=5)
        exact_matches = [fund for fund in exact if fund.fund_name == name_clean]
        if len(exact_matches) == 1:
            return exact_matches[0], 0.85
        if exact_matches:
            return None, 0.0  # ambiguous — requires user confirmation

        if not exact and AKSHARE_AVAILABLE:
            external = await akshare_fund_provider.search_funds(name_clean)
            for record in external[:20]:
                await fund_write_repository.upsert_fund_from_record(record)
            exact = await fund_repository.search_funds(name_clean, limit=5)
            exact_matches = [fund for fund in exact if fund.fund_name == name_clean]
            if len(exact_matches) == 1:
                return exact_matches[0], 0.85

        if len(exact) == 1:
            return exact[0], 0.6
        return None, 0.0

    # ------------------------------------------------------------------
    # Data freshness
    # ------------------------------------------------------------------

    async def ensure_fund_data(self, fund_code: str) -> None:
        """Guarantee local data exists; refresh stale NAVs via the queue.

        Missing fund → inline sync (first view pays once). Stale NAV →
        enqueue a background sync and still serve the stored data.
        """
        fund = await fund_repository.get_fund(fund_code)
        if fund is None:
            try:
                await asyncio.wait_for(
                    fund_sync_service.sync_fund(fund_code),
                    timeout=settings.AKSHARE_TIMEOUT_SECONDS * 2,
                )
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning("fund_inline_sync_failed", fund_code=fund_code, error=str(e))
            return

        if await fund_sync_service.is_nav_stale(fund_code):
            from app.workers.fund_sync import sync_fund_task

            try:
                await sync_fund_task.kiq(fund_code)
                logger.info("fund_sync_enqueued", fund_code=fund_code)
            except Exception as e:
                logger.warning("fund_sync_enqueue_failed", fund_code=fund_code, error=str(e))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_fund_ensuring_data(self, fund_code: str) -> Fund | None:
        """Load a fund, attempting one inline sync when unknown."""
        await self.ensure_fund_data(fund_code)
        return await fund_repository.get_fund(fund_code)

    async def _latest_nav_cached(self, fund_code: str) -> FundNav | None:
        """Cache-aside loader for the latest NAV row."""
        key = cache_key("fund_latest_nav", fund_code)
        cached = await cache_service.get(key)
        if cached:
            row = FundNav(
                fund_code=fund_code,
                nav_date=date.fromisoformat(cached.split("|")[0]),
                unit_nav=float(cached.split("|")[1]) if cached.split("|")[1] != "" else None,
                accumulated_nav=float(cached.split("|")[2]) if cached.split("|")[2] != "" else None,
                daily_return=float(cached.split("|")[3]) if cached.split("|")[3] != "" else None,
            )
            return row

        latest = await fund_repository.get_latest_nav(fund_code)
        if latest is not None:
            await cache_service.set(
                key,
                "|".join(
                    [
                        latest.nav_date.isoformat(),
                        "" if latest.unit_nav is None else str(latest.unit_nav),
                        "" if latest.accumulated_nav is None else str(latest.accumulated_nav),
                        "" if latest.daily_return is None else str(latest.daily_return),
                    ]
                ),
                ttl=_LATEST_NAV_CACHE_TTL_SECONDS,
            )
        return latest

    async def _user_flags(self, fund_code: str, user_id: int) -> tuple[bool, bool]:
        """Check whether the user watchlists or holds this fund."""
        async with get_async_session() as session:
            watchlisted = (
                await session.execute(
                    select(sa_exists().where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code))
                )
            ).scalar()
            held = (
                await session.execute(
                    select(
                        sa_exists().where(
                            col(PortfolioPosition.user_id) == user_id, col(PortfolioPosition.fund_code) == fund_code
                        )
                    )
                )
            ).scalar()
            return bool(watchlisted), bool(held)

    @staticmethod
    def _to_points(history: list[FundNav]) -> list[NavPoint]:
        """Convert NAV rows to analytics points, ascending by date."""
        return [NavPoint(date=row.nav_date, nav=row.unit_nav or 0.0) for row in history]

    @staticmethod
    def _encode_items(items: list[FundSearchItem]) -> str:
        """Serialize search items for the cache."""
        return "[" + ",".join(item.model_dump_json() for item in items) + "]"

    @staticmethod
    def _decode_items(raw: str) -> list[FundSearchItem]:
        """Deserialize cached search items."""
        import json

        return [FundSearchItem.model_validate(entry) for entry in json.loads(raw)]


fund_service = FundService()
