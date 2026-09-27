"""Benchmark index series and the listed-instrument analysis feed.

Index closes live in PostgreSQL and are backfilled on read; the market screen is
fetched through on every visit because a quote nobody asked for is a quote
nobody looked at, and the tables would only drift.
"""

from datetime import date, timedelta
from typing import TypeVar

from pydantic import BaseModel

from app.analytics.returns import NavPoint, range_return
from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.integrations.fund_data.models import CandleExternalBar
from app.integrations.fund_data.normalizer import market_kind, tencent_symbol
from app.integrations.fund_data.tencent_client import (
    fetch_candles,
    fetch_company_profile,
    fetch_minutes,
    fetch_quotes,
    resolve_symbol,
)
from app.repositories.index_repository import index_repository
from app.schemas.fund import NavRange
from app.schemas.market import (
    IndexCatalogItem,
    IndexHistoryResponse,
    IndexPoint,
    IndexQuoteItem,
    MarketPeriod,
    SymbolCompanyResponse,
    SymbolHistoryResponse,
    SymbolIntradayResponse,
    SymbolQuoteResponse,
)
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

# How often each market-screen piece is worth re-asking the feed for. Bars move
# once a day, the snapshot and minute line move all session.
_SYMBOL_QUOTE_TTL_SECONDS = 30
_SYMBOL_INTRADAY_TTL_SECONDS = 60
_SYMBOL_HISTORY_TTL_SECONDS = 600
_COMPANY_TTL_SECONDS = 24 * 3600
# Trading sessions behind each named range, used to size the bar request.
_TRADING_DAYS: dict[str, int] = {"1m": 22, "3m": 63, "6m": 126, "1y": 250, "3y": 750, "all": 1200}
_TRADING_DAYS_PER_WEEK = 5

ModelT = TypeVar("ModelT", bound=BaseModel)


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

    async def get_symbol_quote(self, symbol: str) -> SymbolQuoteResponse | None:
        """Snapshot of one listed instrument, or None for an unusable code.

        The code is canonicalized through a shape whitelist before it reaches the
        feed, so an unvalidated string can never be interpolated into a request.
        """
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_quote", canonical)
        cached = await _read_cache(key, SymbolQuoteResponse)
        if cached is not None:
            return cached

        quotes = await fetch_quotes([canonical])
        if not quotes:
            logger.warning("market_quote_empty", symbol=canonical)
            return None

        response = SymbolQuoteResponse.model_validate(quotes[0].model_dump())
        await _write_cache(key, response, _SYMBOL_QUOTE_TTL_SECONDS)
        return response

    async def get_symbol_history(
        self, symbol: str, period: MarketPeriod, range_key: NavRange
    ) -> SymbolHistoryResponse | None:
        """Adjusted bars for one instrument, trimmed to the requested window."""
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_history", canonical, period, range_key)
        cached = await _read_cache(key, SymbolHistoryResponse)
        if cached is not None:
            return cached

        bars = await fetch_candles(await resolve_symbol(canonical), period, _bar_count(period, range_key))
        if not bars:
            logger.warning("market_history_empty", symbol=canonical, period=period)
            return None

        start = range_start(range_key, business_today())
        window = [bar for bar in bars if start is None or bar.trade_date >= start]
        response = SymbolHistoryResponse(
            symbol=canonical,
            kind=market_kind(canonical),
            period=period,
            range=range_key,
            bars=window,
            total=len(window),
            period_return=_bars_change(window),
        )
        await _write_cache(key, response, _SYMBOL_HISTORY_TTL_SECONDS)
        return response

    async def get_symbol_intraday(self, symbol: str) -> SymbolIntradayResponse | None:
        """The current session's minute line; empty outside trading hours."""
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_intraday", canonical)
        cached = await _read_cache(key, SymbolIntradayResponse)
        if cached is not None:
            return cached

        series = await fetch_minutes(canonical)
        if not series.points:
            logger.info("market_intraday_empty", symbol=canonical)
            return None

        response = SymbolIntradayResponse(
            symbol=canonical,
            kind=market_kind(canonical),
            trade_date=series.trade_date,
            prev_close=series.prev_close,
            points=series.points,
            total=len(series.points),
        )
        await _write_cache(key, response, _SYMBOL_INTRADAY_TTL_SECONDS)
        return response

    async def get_symbol_company(self, symbol: str) -> SymbolCompanyResponse | None:
        """Company master data. A missing record is a hidden card, not an error.

        This is the one piece served by Eastmoney rather than the quote feed, and
        that host answers intermittently from here, so a failure is logged and
        reported as "no profile" instead of taking the chart down with it.
        """
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_company", canonical)
        cached = await _read_cache(key, SymbolCompanyResponse)
        if cached is not None:
            return cached

        try:
            company = await fetch_company_profile(canonical)
        except Exception as e:
            logger.warning("market_company_fetch_failed", symbol=canonical, error=str(e))
            company = None

        response = SymbolCompanyResponse(symbol=canonical, company=company)
        # Only a real record is worth holding; a miss should be retried next time.
        if company is not None:
            await _write_cache(key, response, _COMPANY_TTL_SECONDS)
        return response

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


def _bar_count(period: MarketPeriod, range_key: NavRange) -> int:
    """Bars to request so the window is covered without fetching a decade."""
    days = _TRADING_DAYS[range_key]
    if period == "week":
        return max(days // _TRADING_DAYS_PER_WEEK, 8)
    return days


def _bars_change(bars: list[CandleExternalBar]) -> float | None:
    """Cumulative close-to-close change across the returned bars."""
    return _window_change([IndexPoint(trade_date=bar.trade_date, close=bar.close) for bar in bars])


async def _read_cache(key_parts: tuple[str, ...], model: type[ModelT]) -> ModelT | None:
    """Serve a stored response, treating a bad record as a miss."""
    raw = await cache_service.get(cache_key(*key_parts))
    if not raw:
        return None
    try:
        return model.model_validate_json(raw)
    except ValueError:
        logger.warning("market_cache_invalid", key=key_parts[0])
        return None


async def _write_cache(key_parts: tuple[str, ...], model: BaseModel, ttl: int) -> None:
    await cache_service.set(cache_key(*key_parts), model.model_dump_json(), ttl=ttl)


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
