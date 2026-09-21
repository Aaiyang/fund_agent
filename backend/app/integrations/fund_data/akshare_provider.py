"""AKShare-backed FundDataProvider with bounded concurrency isolation.

AKShare calls are synchronous and blocking; every call runs in a worker
thread via asyncio.to_thread, gated by a semaphore (bounded concurrency), a
minimum-interval throttle, a per-call timeout and tenacity retries
(MVP spec 7.6). Configuration comes exclusively from environment variables.
"""

import asyncio
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
)
from app.integrations.fund_data.normalizer import (
    normalize_fund_record,
    normalize_nav_rows,
    normalize_profile_rows,
)
from app.utils.sanitization import sanitize_string

# Cache the full open-fund rank table in-process for cheap search + latest NAV
_RANK_CACHE_TTL_SECONDS = 6 * 3600


class AKShareFundProvider:
    """Bounded-concurrency adapter around AKShare's synchronous fund APIs."""

    def __init__(self) -> None:
        """Initialize bounded-concurrency primitives and caches."""
        self._semaphore = asyncio.Semaphore(settings.AKSHARE_MAX_CONCURRENCY)
        self._throttle_lock = asyncio.Lock()
        self._last_call_monotonic = 0.0
        self._rank_records: list[dict[str, Any]] = []
        self._rank_cached_at = 0.0

    # ------------------------------------------------------------------
    # Public API (FundDataProvider)
    # ------------------------------------------------------------------

    async def search_funds(self, keyword: str) -> list[FundExternalRecord]:
        """Search funds by code prefix or fuzzy name from the rank table."""
        records = await self._get_rank_records()
        keyword_clean = sanitize_string(keyword).strip()
        if not keyword_clean:
            return []
        lowered = keyword_clean.lower()
        matched = [
            record
            for record in records
            if lowered in str(record.get("fund_code", "")).lower()
            or lowered in str(record.get("fund_name", "")).lower()
        ]
        return [item for record in matched[:50] if (item := normalize_fund_record(record)) is not None]

    async def get_fund_profile(self, fund_code: str) -> FundExternalProfile | None:
        """Fetch fund master data from the individual basic-info endpoint."""
        rows = await self._call("fund_individual_basic_info_xq", symbol=fund_code)
        return normalize_profile_rows(rows, fund_code)

    async def get_latest_nav(self, fund_code: str) -> FundExternalNav | None:
        """Fetch the most recent NAV, preferring the rank table then history."""
        records = await self._get_rank_records()
        for record in records:
            if str(record.get("fund_code", "")).zfill(6) == fund_code:
                if (normalized := normalize_fund_record(record)) is not None:
                    return FundExternalNav(
                        fund_code=fund_code,
                        nav_date=normalized.nav_date or date.today(),
                        unit_nav=normalized.latest_nav,
                        daily_return=normalized.daily_return,
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

    async def get_fund_manager(self, fund_code: str) -> FundExternalManager | None:
        """Fetch the current manager from the basic-info endpoint."""
        profile = await self.get_fund_profile(fund_code)
        if profile is None:
            return None
        return FundExternalManager(fund_code=fund_code, manager_name=profile.manager_name)

    async def get_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        """Stock holdings are not part of the MVP sync scope (spec 5.7)."""
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_rank_records(self) -> list[dict[str, Any]]:
        """Return the (cached) open-fund rank table as plain dict records."""
        if self._rank_records and (time.monotonic() - self._rank_cached_at) < _RANK_CACHE_TTL_SECONDS:
            return self._rank_records
        rows = await self._call("fund_open_fund_rank_em", symbol="全部")
        self._rank_records = rows or []
        self._rank_cached_at = time.monotonic()
        return self._rank_records

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

        async with self._semaphore:
            await self._throttle()
            try:
                records = await asyncio.wait_for(
                    asyncio.to_thread(self._call_sync, func_name, *args, **kwargs),
                    timeout=settings.AKSHARE_TIMEOUT_SECONDS,
                )
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
