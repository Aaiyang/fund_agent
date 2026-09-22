"""Benchmark index series: PostgreSQL first, provider backfill when the range is uncovered."""

from datetime import date, timedelta

from app.analytics.returns import NavPoint, range_return
from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.repositories.index_repository import index_repository
from app.schemas.fund import NavRange
from app.schemas.market import IndexCatalogItem, IndexHistoryResponse, IndexPoint
from app.utils.clock import business_today, range_start

# The picker's fixed catalog. Codes are looked up here before reaching AKShare,
# so no caller-controlled string is ever passed to the third-party client.
BENCHMARK_INDEXES: dict[str, str] = {
    "sh000300": "沪深300",
    "sz399006": "创业板指",
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000012": "国债指数",
}

# Public series that moves once a day: one provider pull per index per window.
_SYNC_TTL_SECONDS = 6 * 3600
_STALE_DAYS = 3


class MarketService:
    """Reads benchmark closes and tops them up from the provider on demand."""

    def catalog(self) -> list[IndexCatalogItem]:
        """Selectable benchmarks, in picker order."""
        return [IndexCatalogItem(index_code=code, name=name) for code, name in BENCHMARK_INDEXES.items()]

    async def get_history(self, index_code: str, range_key: NavRange) -> IndexHistoryResponse | None:
        """Closes plus the window's cumulative change for one benchmark.

        Returns:
            The series, or None when `index_code` is not a known benchmark.
        """
        name = BENCHMARK_INDEXES.get(index_code)
        if name is None:
            logger.info("index_unknown_code", index_code=index_code)
            return None

        today = business_today()
        start = range_start(range_key, today)
        await self._ensure_stored(index_code, start, today)
        rows = await index_repository.get_history(index_code, start, today)
        points = [IndexPoint(trade_date=row.trade_date, close=row.close) for row in rows]
        return IndexHistoryResponse(
            index_code=index_code,
            name=name,
            range=range_key,
            points=points,
            period_return=_window_change(points),
        )

    async def _ensure_stored(self, index_code: str, start: date | None, today: date) -> None:
        """Pull the full daily series when what is stored cannot serve the range."""
        coverage = await index_repository.get_coverage(index_code)
        if coverage is not None and _covers(coverage, start, today):
            return
        if not await cache_service.acquire_lock(cache_key("index_sync", index_code), ttl=_SYNC_TTL_SECONDS):
            return

        quotes = await akshare_fund_provider.get_index_history(index_code)
        if not quotes:
            logger.warning("index_history_empty", index_code=index_code)
            return
        await index_repository.upsert_quotes(quotes)
        logger.info("index_history_synced", index_code=index_code, rows=len(quotes))


def _covers(coverage: tuple[date, date], start: date | None, today: date) -> bool:
    """True when the stored series spans the requested window and is recent."""
    earliest, latest = coverage
    if start is not None and earliest > start:
        return False
    return latest >= today - timedelta(days=_STALE_DAYS)


def _window_change(points: list[IndexPoint]) -> float | None:
    """Cumulative close-to-close change across the returned window."""
    if len(points) < 2:
        return None
    series = [NavPoint(date=point.trade_date, nav=point.close) for point in points]
    return range_return(series, series[0].date, series[-1].date)


market_service = MarketService()
