"""Fund domain service: search, detail, NAV history, performance, resolve.

All fund facts come from FundService — other services, the API layer and the
future Agent tools never touch fund data providers directly (spec 14.1).
Online reads prefer PostgreSQL, with Redis as a hot cache; external sync is
enqueued or inlined only when local data is missing or stale (spec 5.6).
"""

import asyncio
import json
from datetime import date, timedelta

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
    NavRange,
)
from app.services.fund_sync_service import fund_sync_service
from app.utils.clock import business_today, range_start

_LATEST_NAV_CACHE_TTL_SECONDS = 300
_SEARCH_CACHE_TTL_SECONDS = 300


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

        funds = await self._search_fund_rows(keyword_clean)
        if not funds:
            return []

        codes = [fund.fund_code for fund in funds]
        navs = await fund_repository.get_latest_navs(codes)
        missing = [code for code in codes if code not in navs]
        if missing:
            navs = await self._backfill_navs(missing, codes)
        watchlisted, held = await self._user_flag_sets(user_id)
        return [
            FundSearchItem(
                fund_code=fund.fund_code,
                fund_name=fund.fund_name,
                fund_type=fund.fund_type,
                latest_nav=nav.unit_nav if nav else None,
                nav_date=nav.nav_date if nav else None,
                daily_return=nav.daily_return if nav else None,
                is_watchlisted=fund.fund_code in watchlisted,
                is_held=fund.fund_code in held,
            )
            for fund in funds
            for nav in [navs.get(fund.fund_code)]
        ]

    async def _backfill_navs(self, missing: list[str], codes: list[str]) -> dict[str, FundNav]:
        """Store NAVs for search hits that have none, then re-read PostgreSQL.

        Funds discovered before their NAV was persisted (or synced by another
        user) would otherwise list `--` for 净值/涨跌, which spec 3.4 requires.
        Reads still come from PostgreSQL; the provider only fills the gap.
        """
        if AKSHARE_AVAILABLE:
            try:
                external = await akshare_fund_provider.get_latest_navs(missing)
                if external:
                    await fund_write_repository.upsert_navs(external)
            except Exception as e:
                logger.warning("fund_nav_backfill_failed", count=len(missing), error=str(e))
        return await fund_repository.get_latest_navs(codes)

    async def _search_fund_rows(self, keyword_clean: str) -> list[Fund]:
        """Load matching fund master rows, caching the shared result set.

        Only public data is cached; per-user flags stay out of the key so one
        user's watchlist edit can never be masked by another's cache entry —
        and never by their own, since flags are read live.
        """
        cached = await cache_service.get(cache_key("fund_search", keyword_clean))
        if cached:
            return self._decode_funds(cached)

        local_funds = await fund_repository.search_funds(keyword_clean)
        if not local_funds and AKSHARE_AVAILABLE:
            try:
                external = await akshare_fund_provider.search_funds(keyword_clean)
            except Exception as e:
                # A provider outage is an empty result page, not a 500: the
                # caller already sees local matches when the table has them.
                logger.warning("fund_external_search_failed", keyword=keyword_clean, error=str(e))
                external = []
            for record in external[:50]:
                await fund_write_repository.upsert_fund_from_record(record)
            local_funds = await fund_repository.search_funds(keyword_clean)
            # A 6-digit code missing from the rank table (exchange-traded funds,
            # recent issues) still resolves by fetching that fund directly.
            if not local_funds and len(keyword_clean) == 6 and keyword_clean.isdigit():
                await fund_sync_service.sync_fund(keyword_clean)
                local_funds = await fund_repository.search_funds(keyword_clean)

        funds = local_funds[:50]
        if funds:
            await cache_service.set(
                cache_key("fund_search", keyword_clean),
                self._encode_funds(funds),
                ttl=_SEARCH_CACHE_TTL_SECONDS,
            )
        return funds

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

        end = latest.nav_date if latest else business_today()
        return FundDetailResponse(
            fund_code=fund.fund_code,
            fund_name=fund.fund_name,
            fund_type=fund.fund_type,
            company=fund.company,
            manager_name=fund.manager_name,
            inception_date=fund.inception_date,
            asset_size=fund.asset_size,
            benchmark=fund.benchmark,
            latest_nav=latest.unit_nav if latest else None,
            accumulated_nav=latest.accumulated_nav if latest else None,
            nav_date=latest.nav_date if latest else None,
            daily_return=latest.daily_return if latest else None,
            performance=self._compute_performance(points, end),
            is_watchlisted=is_watchlisted,
            is_held=is_held,
            source=fund.source,
            # AKShare's rank table carries no as-of column; the newest NAV date
            # we hold is the honest equivalent for "what this data describes".
            source_as_of=fund.source_as_of or (latest.nav_date if latest else None),
            updated_at=fund.updated_at or fund.fetched_at,
            nav_fetched_at=latest.fetched_at if latest else None,
        )

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        range_key: NavRange | None = None,
        limit: int | None = None,
        before_date: date | None = None,
    ) -> FundNavHistoryResponse:
        """Return the stored NAV series for charting (no live pass-through).

        Args:
            fund_code: The 6-digit fund code.
            start_date: Explicit lower bound; overridden by `range_key`.
            end_date: Explicit upper bound.
            range_key: Named range from spec 3.5.3 (1m/3m/6m/1y/3y/all).
            limit: Keep only the newest N points, for paging the history list.
            before_date: Exclusive cursor — only points strictly older than this,
                so a client can walk backwards without repeating a page.
        """
        await self.ensure_fund_data(fund_code)
        if range_key is not None:
            start_date = range_start(range_key, business_today())
        if before_date is not None:
            cursor_end = before_date - timedelta(days=1)
            end_date = min(end_date, cursor_end) if end_date else cursor_end
        history = await fund_repository.get_nav_history(fund_code, start_date, end_date)
        page, has_more = _newest_page(history, limit)
        return FundNavHistoryResponse(
            fund_code=fund_code,
            range=range_key,
            total=len(history),
            has_more=has_more,
            points=[
                FundNavPoint(
                    nav_date=row.nav_date,
                    unit_nav=row.unit_nav,
                    accumulated_nav=row.accumulated_nav,
                    daily_return=row.daily_return,
                )
                for row in page
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
            except Exception:
                logger.exception("fund_inline_sync_failed", fund_code=fund_code)
            return

        if await fund_sync_service.is_nav_stale(fund_code):
            try:
                await fund_sync_service.enqueue_sync(fund_code)
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
            return FundNav.model_validate(json.loads(cached))

        latest = await fund_repository.get_latest_nav(fund_code)
        if latest is not None:
            await cache_service.set(
                key,
                json.dumps(
                    {
                        "fund_code": latest.fund_code,
                        "nav_date": latest.nav_date.isoformat(),
                        "unit_nav": latest.unit_nav,
                        "accumulated_nav": latest.accumulated_nav,
                        "daily_return": latest.daily_return,
                        "fetched_at": latest.fetched_at.isoformat() if latest.fetched_at else None,
                    }
                ),
                ttl=_LATEST_NAV_CACHE_TTL_SECONDS,
            )
        return latest

    async def _user_flags(self, fund_code: str, user_id: int) -> tuple[bool, bool]:
        """Check whether the user watchlists or holds this fund."""
        watchlisted, held = await self._user_flag_sets(user_id)
        return fund_code in watchlisted, fund_code in held

    async def _user_flag_sets(self, user_id: int) -> tuple[set[str], set[str]]:
        """Fund codes the user watchlists, and fund codes the user holds."""
        async with get_async_session() as session:
            watchlisted = set(
                (await session.execute(select(col(Watchlist.fund_code)).where(col(Watchlist.user_id) == user_id)))
                .scalars()
                .all()
            )
            held = set(
                (
                    await session.execute(
                        select(col(PortfolioPosition.fund_code))
                        .where(col(PortfolioPosition.user_id) == user_id)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            return watchlisted, held

    @staticmethod
    def _to_points(history: list[FundNav]) -> list[NavPoint]:
        """Convert NAV rows to analytics points, ascending by date.

        Rows without a unit NAV are dropped rather than read as 0.0: a zero on
        the series makes every window anchored on it report a -100% return and
        a -100% maximum drawdown.
        """
        return [NavPoint(date=row.nav_date, nav=row.unit_nav) for row in history if row.unit_nav is not None]

    @staticmethod
    def _encode_funds(funds: list[Fund]) -> str:
        """Serialize the public part of search hits for the shared cache."""
        return json.dumps(
            [{"fund_code": fund.fund_code, "fund_name": fund.fund_name, "fund_type": fund.fund_type} for fund in funds]
        )

    @staticmethod
    def _decode_funds(raw: str) -> list[Fund]:
        """Deserialize cached search hits back into fund master rows."""
        return [Fund.model_validate(entry) for entry in json.loads(raw)]


def _newest_page(history: list[FundNav], limit: int | None) -> tuple[list[FundNav], bool]:
    """Keep the newest `limit` rows of an ascending series; report older remainders.

    Rows arrive ascending, so the tail is the most recent window and everything
    before it is the next page walked backwards by cursor.
    """
    if limit is None or len(history) <= limit:
        return history, False
    return history[-limit:], True


fund_service = FundService()
