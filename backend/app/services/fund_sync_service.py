"""Fund sync orchestration: lock-guarded, idempotent external data sync."""

import asyncio
from datetime import date, datetime, timedelta

from app.core.cache import cache_service
from app.core.config import settings
from app.core.logging import logger
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.repositories.fund_repository import fund_repository, fund_write_repository
from app.utils.clock import utc_now


class FundSyncService:
    """Syncs one or many funds from the external provider into PostgreSQL.

    Deduplication: a Redis distributed lock keyed by
    ``fund_sync:{fund_code}:{business_date}`` lets only one worker sync a
    given fund per business date (MVP spec 7.12). Upserts make retries
    idempotent — re-running never duplicates rows.
    """

    async def sync_fund(self, fund_code: str, include_profile: bool = True) -> bool:
        """Sync master data + NAV history for one fund.

        Args:
            fund_code: The 6-digit fund code.
            include_profile: Also fetch basic profile info.

        Returns:
            True when new data was written, False when skipped or failed.
        """
        lock_key = f"fund_sync:{fund_code}:{date.today().isoformat()}"
        if not await cache_service.acquire_lock(lock_key, ttl=600):
            logger.debug("fund_sync_skipped_locked", fund_code=fund_code)
            return False

        try:
            written = False
            if include_profile:
                profile = await akshare_fund_provider.get_fund_profile(fund_code)
                if profile is not None:
                    await fund_write_repository.upsert_fund_from_record(profile)
                    written = True

            navs = await akshare_fund_provider.get_nav_history(fund_code)
            if navs:
                await fund_write_repository.upsert_navs(navs)
                written = True

            logger.info(
                "fund_sync_completed",
                fund_code=fund_code,
                nav_rows=len(navs),
                wrote=written,
            )
            return written
        except Exception as e:
            logger.exception("fund_sync_failed", fund_code=fund_code, error=str(e))
            return False
        finally:
            await cache_service.release_lock(lock_key)

    async def sync_funds_bounded(self, fund_codes: list[str], concurrency: int = 5) -> dict[str, int]:
        """Sync many funds with bounded concurrency (MVP spec 7.7).

        Args:
            fund_codes: Fund codes to sync.
            concurrency: Maximum simultaneous provider calls.

        Returns:
            A summary dict: synced / skipped / failed counts.
        """
        semaphore = asyncio.Semaphore(min(concurrency, 10))

        async def _bounded_sync(code: str) -> bool:
            async with semaphore:
                return await self.sync_fund(code)

        results = await asyncio.gather(*[_bounded_sync(code) for code in fund_codes])
        summary = {
            "total": len(fund_codes),
            "synced": sum(1 for ok in results if ok),
            "skipped_or_failed": sum(1 for ok in results if not ok),
        }
        logger.info("fund_batch_sync_completed", **summary)
        return summary

    async def sync_hot_funds(self) -> dict[str, int]:
        """Sync all Hot Funds (held or watchlisted by any user)."""
        codes = await fund_repository.get_hot_fund_codes()
        if not codes:
            logger.info("fund_hot_sync_no_targets")
            return {"total": 0, "synced": 0, "skipped_or_failed": 0}
        return await self.sync_funds_bounded(codes)

    async def is_nav_stale(self, fund_code: str) -> bool:
        """True when the latest stored NAV is older than the staleness budget."""
        latest = await fund_repository.get_latest_nav(fund_code)
        if latest is None:
            return True
        cutoff = utc_now() - timedelta(hours=settings.FUND_NAV_STALE_HOURS)
        fetched = latest.fetched_at or datetime.combine(latest.nav_date, datetime.min.time())
        return fetched < cutoff


fund_sync_service = FundSyncService()
