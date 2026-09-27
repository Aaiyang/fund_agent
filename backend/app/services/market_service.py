"""Benchmark index series: PostgreSQL first, provider backfill when the range is uncovered."""

from datetime import date, timedelta

from app.analytics.returns import NavPoint, range_return
from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.repositories.index_repository import index_repository
from app.schemas.fund import NavRange
from app.schemas.market import IndexCatalogItem, IndexHistoryResponse, IndexPoint, IndexQuoteItem
from app.utils.clock import business_today, range_start

# The picker's fixed catalog. Codes are looked up here before reaching AKShare,
# so no caller-controlled string is ever passed to the third-party client.
# Order is the home tape's order: the two broad market gauges first.
BENCHMARK_INDEXES: dict[str, str] = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sz399006": "创业板指",
    "sh000012": "国债指数",
}

# Public series that moves once a day: one provider pull per index per window.
_SYNC_TTL_SECONDS = 6 * 3600
_STALE_DAYS = 3
# Long enough to always hold two trading days, including a holiday stretch.
_QUOTE_LOOKBACK_DAYS = 20


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

    async def get_quotes(self) -> list[IndexQuoteItem]:
        """Latest close and day change for every catalog index, picker order.

        The tape is public data with no per-user part, so it is safe to serve
        from the same stored series the chart uses; a cold index just pays one
        provider pull here as it would on the fund page.
        """
        today = business_today()
        start = today - timedelta(days=_QUOTE_LOOKBACK_DAYS)
        quotes: list[IndexQuoteItem] = []
        for code, name in BENCHMARK_INDEXES.items():
            await self._ensure_stored(code, start, today)
            rows = await index_repository.get_history(code, start, today)
            closes = [row.close for row in rows if row.close is not None]
            quotes.append(
                IndexQuoteItem(
                    index_code=code,
                    name=name,
                    close=closes[-1] if closes else None,
                    change_pct=_daily_change(closes),
                    trade_date=rows[-1].trade_date if rows else None,
                )
            )
        return quotes

    async def _ensure_stored(self, index_code: str, start: date | None, today: date) -> None:
        """Pull the full daily series when what is stored cannot serve the range."""
        coverage = await index_repository.get_coverage(index_code)
        if coverage is not None and _covers(coverage, start, today):
            return
        lock_key = cache_key("index_sync", index_code)
        if not await cache_service.acquire_lock(lock_key, ttl=_SYNC_TTL_SECONDS):
            return

        try:
            quotes = await akshare_fund_provider.get_index_history(index_code)
            if quotes:
                await index_repository.upsert_quotes(quotes)
                logger.info("index_history_synced", index_code=index_code, rows=len(quotes))
            else:
                logger.warning("index_history_empty", index_code=index_code)
        except Exception as e:
            # A read must not 500 because the benchmark source is unhappy:
            # serve whatever is already stored, and let the next request retry.
            logger.warning("index_history_sync_failed", index_code=index_code, error=str(e))
            await cache_service.release_lock(lock_key)


def _daily_change(closes: list[float]) -> float | None:
    """Close-to-close change of the last two sessions, in percent points."""
    if len(closes) < 2 or not closes[-2]:
        return None
    return round((closes[-1] - closes[-2]) / closes[-2] * 100, 4)


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
