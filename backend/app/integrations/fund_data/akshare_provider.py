"""AKShare-backed FundDataProvider with bounded concurrency isolation.

AKShare calls are synchronous and blocking; every call runs in a worker
thread via asyncio.to_thread, gated by a semaphore (bounded concurrency), a
minimum-interval throttle, a per-call timeout and tenacity retries
(MVP spec 7.6). Configuration comes exclusively from environment variables.
"""

import asyncio
import functools
import logging
import time
from datetime import date
from typing import Any

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger
from app.integrations.fund_data.akshare_client import AKSHARE_AVAILABLE, ak
from app.integrations.fund_data.models import (
    FundExternalHolding,
    FundExternalManager,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
    IndexExternalQuote,
    StockExternalQuote,
)
from app.integrations.fund_data.normalizer import (
    normalize_fund_record,
    normalize_holding_rows,
    normalize_index_rows,
    normalize_nav_rows,
    normalize_profile_rows,
    parse_quarter,
    sina_symbol,
)
from app.integrations.fund_data.sina_client import fetch_quotes
from app.utils.clock import business_today
from app.utils.sanitization import sanitize_string

# Cache the full open-fund rank table in-process for cheap search + latest NAV
_RANK_CACHE_TTL_SECONDS = 6 * 3600


def match_records(records: list[FundExternalRecord], keyword: str) -> list[FundExternalRecord]:
    """Substring match on code or name.

    AKShare's rank endpoint returns the whole table with no query API, so
    fuzzy search happens here. Chinese names match as substrings, which is
    what users type ("华泰柏瑞" finds "华泰柏瑞质量成长混合C").
    """
    lowered = keyword.lower()
    return [record for record in records if lowered in record.fund_code or lowered in record.fund_name.lower()]


class AKShareFundProvider:
    """Bounded-concurrency adapter around AKShare's synchronous fund APIs."""

    def __init__(self) -> None:
        """Initialize bounded-concurrency primitives and caches."""
        self._semaphore = asyncio.Semaphore(settings.AKSHARE_MAX_CONCURRENCY)
        self._throttle_lock = asyncio.Lock()
        self._last_call_monotonic = 0.0
        self._rank_index: list[FundExternalRecord] = []
        self._rank_cached_at = 0.0

    # ------------------------------------------------------------------
    # Public API (FundDataProvider)
    # ------------------------------------------------------------------

    async def search_funds(self, keyword: str) -> list[FundExternalRecord]:
        """Search funds by code substring or fuzzy name from the rank table."""
        keyword_clean = sanitize_string(keyword).strip()
        if not keyword_clean:
            return []
        index = await self._get_rank_index()
        return match_records(index, keyword_clean)[:50]

    async def get_fund_profile(self, fund_code: str) -> FundExternalProfile | None:
        """Fetch fund master data from the individual basic-info endpoint."""
        rows = await self._call("fund_individual_basic_info_xq", symbol=fund_code)
        return normalize_profile_rows(rows, fund_code)

    async def get_latest_nav(self, fund_code: str) -> FundExternalNav | None:
        """Fetch the most recent NAV, preferring the rank table then history."""
        index = await self._get_rank_index()
        for record in index:
            # A row with no NAV date is skipped rather than dated "today":
            # fabricating a date would write a fund_nav point on a possibly
            # non-trading day and anchor every later window calculation on it.
            if record.fund_code == fund_code and record.nav_date is not None:
                return FundExternalNav(
                    fund_code=fund_code,
                    nav_date=record.nav_date,
                    unit_nav=record.latest_nav,
                    daily_return=record.daily_return,
                )
        history = await self.get_nav_history(fund_code)
        return history[0] if history else None

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundExternalNav]:
        """Fetch and merge unit/accumulated NAV history."""
        unit_rows = await self._call("fund_open_fund_info_em", symbol=fund_code, indicator="单位净值走势")
        accumulated_rows: list[dict[str, Any]] = []
        try:
            accumulated_rows = await self._call("fund_open_fund_info_em", symbol=fund_code, indicator="累计净值走势")
        except Exception as e:
            logger.warning("fund_accumulated_nav_unavailable", fund_code=fund_code, error=str(e))

        navs = normalize_nav_rows(unit_rows or [], accumulated_rows, fund_code)
        if end_date is not None:
            navs = [nav for nav in navs if nav.nav_date <= end_date]
        if start_date is not None:
            navs = [nav for nav in navs if nav.nav_date >= start_date]
        return navs

    async def get_latest_navs(self, fund_codes: list[str]) -> list[FundExternalNav]:
        """Read the latest NAV for many funds from the cached rank table."""
        if not fund_codes:
            return []
        wanted = set(fund_codes)
        index = await self._get_rank_index()
        return [
            FundExternalNav(
                fund_code=record.fund_code,
                nav_date=record.nav_date,
                unit_nav=record.latest_nav,
                daily_return=record.daily_return,
            )
            for record in index
            if record.fund_code in wanted and record.latest_nav is not None and record.nav_date is not None
        ]

    async def get_fund_manager(self, fund_code: str) -> FundExternalManager | None:
        """Fetch the current manager from the basic-info endpoint."""
        profile = await self.get_fund_profile(fund_code)
        if profile is None:
            return None
        return FundExternalManager(fund_code=fund_code, manager_name=profile.manager_name)

    async def get_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        """Fetch the disclosed stock holdings of the two latest reporting quarters.

        The quarter-over-quarter change the UI shows needs the previous
        disclosure too, and the endpoint is yearly, so the year before is only
        pulled when the current one has a single quarter published.
        """
        year = business_today().year
        rows: list[dict[str, Any]] = []
        for candidate in (year, year - 1):
            rows.extend(await self._call("fund_portfolio_hold_em", symbol=fund_code, date=str(candidate)))
            quarters = {parse_quarter(row.get("季度")) for row in rows}
            if len(quarters - {None}) >= 2:
                break
        return normalize_holding_rows(rows, fund_code)

    async def get_stock_quotes(self, stock_codes: list[str]) -> list[StockExternalQuote]:
        """Quote holdings across A-share/HK/US markets in one batched request."""
        symbols = [symbol for symbol in (sina_symbol(code) for code in stock_codes) if symbol]
        if not symbols:
            return []
        try:
            return await fetch_quotes(symbols)
        except Exception as e:
            # A quote outage costs one column, not the whole holdings page.
            logger.warning("stock_quotes_unavailable", count=len(symbols), error=str(e))
            return []

    async def get_index_history(
        self,
        index_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[IndexExternalQuote]:
        """Fetch a benchmark index's daily closes for the comparison line.

        Outside the FundDataProvider protocol: an index is not a fund fact. It
        shares this adapter only for the guarded transport (throttle, semaphore,
        timeout, retries). The Sina endpoint returns the whole history in one
        call, so the range is trimmed here; the Eastmoney index endpoint is
        unreachable from some networks.
        """
        rows = await self._call("stock_zh_index_daily", symbol=index_code)
        quotes = normalize_index_rows(rows or [], index_code)
        if start_date is not None:
            quotes = [quote for quote in quotes if quote.trade_date >= start_date]
        if end_date is not None:
            quotes = [quote for quote in quotes if quote.trade_date <= end_date]
        return quotes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_rank_index(self) -> list[FundExternalRecord]:
        """Return the open-fund rank table as normalized records, cached.

        Normalization happens once per refresh: the raw rows carry Chinese
        column names, and matching on English keys would silently never hit.
        """
        if self._rank_index and (time.monotonic() - self._rank_cached_at) < _RANK_CACHE_TTL_SECONDS:
            return self._rank_index
        rows = await self._call("fund_open_fund_rank_em", symbol="全部")
        normalized = [item for row in rows or [] if (item := normalize_fund_record(row)) is not None]
        if normalized:
            self._rank_index = normalized
            self._rank_cached_at = time.monotonic()
            logger.info("akshare_rank_index_built", rows=len(normalized))
        return normalized

    async def _throttle(self) -> None:
        """Enforce a minimum interval between external calls."""
        async with self._throttle_lock:
            elapsed = time.monotonic() - self._last_call_monotonic
            wait = settings.AKSHARE_MIN_INTERVAL_SECONDS - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_monotonic = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call(self, func_name: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Run one AKShare function in a thread with throttle+semaphore+timeout."""
        if not AKSHARE_AVAILABLE or ak is None:
            logger.warning("akshare_not_available", func_name=func_name)
            return []

        # The permit is returned by the worker thread's completion callback, not
        # when this coroutine resumes: a started thread cannot be cancelled, so
        # releasing on timeout would let real concurrency creep past
        # AKSHARE_MAX_CONCURRENCY by one stuck call at a time.
        await self._semaphore.acquire()
        try:
            # run_in_executor forwards positional args only: every AKShare
            # function here is called with keyword arguments (symbol, indicator),
            # so they must be bound before the call or the executor rejects them.
            future = asyncio.get_running_loop().run_in_executor(
                None, functools.partial(self._call_sync, func_name, *args, **kwargs)
            )
        except Exception:
            self._semaphore.release()
            raise
        future.add_done_callback(lambda _future: self._semaphore.release())

        try:
            await self._throttle()
            records = await asyncio.wait_for(future, timeout=settings.AKSHARE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "akshare_call_timeout",
                func_name=func_name,
                timeout_seconds=settings.AKSHARE_TIMEOUT_SECONDS,
            )
            raise TimeoutError(f"akshare call {func_name} timed out")
        except Exception as e:
            logger.warning("akshare_call_failed", func_name=func_name, error=str(e))
            raise
        logger.debug("akshare_call_successful", func_name=func_name, rows=len(records))
        return records

    def _call_sync(self, func_name: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Blocking AKShare invocation — always runs inside a worker thread."""
        func = getattr(ak, func_name, None)
        if func is None:
            raise ValueError(f"akshare function not found: {func_name}")
        frame = func(*args, **kwargs)
        return frame.to_dict("records")


akshare_fund_provider = AKShareFundProvider()
