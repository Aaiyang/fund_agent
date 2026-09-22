"""Fund sync orchestration: lock-guarded, idempotent external data sync."""

import asyncio
from datetime import timedelta

from app.core.cache import cache_key, cache_service
from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import fund_sync_total
from app.core.task_queue import enqueue
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.repositories.fund_repository import fund_repository, fund_write_repository
from app.repositories.job_repository import job_repository
from app.utils.clock import business_close_utc, business_today, utc_now
from app.workers import FUND_SYNC_TASK


class FundSyncService:
    """Syncs one or many funds from the external provider into PostgreSQL.

    Deduplication: a Redis distributed lock keyed by
    ``fund_sync:{fund_code}:{business_date}`` lets only one worker sync a
    given fund per business date (MVP spec 7.12). Upserts make retries
    idempotent — re-running never duplicates rows.
    """

    async def sync_fund(self, fund_code: str, include_profile: bool = True) -> str:
        """Sync master data + NAV history for one fund.

        Args:
            fund_code: The 6-digit fund code.
            include_profile: Also fetch basic profile info.

        Returns:
            One of "written" (new data stored), "skipped" (another worker holds
            the lock for this fund/date) or "failed". The worker ledger needs
            the difference: a skip is not a failure.
        """
        lock_key = f"fund_sync:{fund_code}:{business_today().isoformat()}"
        if not await cache_service.acquire_lock(lock_key, ttl=600):
            fund_sync_total.labels(status="skipped").inc()
            logger.debug("fund_sync_skipped_locked", fund_code=fund_code)
            return "skipped"

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

            if written:
                # Cache-aside: PostgreSQL is the source of truth, so the hot
                # entry must not keep serving the pre-sync NAV (spec 7.14).
                await cache_service.delete(cache_key("fund_latest_nav", fund_code))

            fund_sync_total.labels(status="written").inc()
            logger.info(
                "fund_sync_completed",
                fund_code=fund_code,
                nav_rows=len(navs),
                wrote=written,
            )
            return "written" if written else "skipped"
        except Exception as e:
            fund_sync_total.labels(status="failed").inc()
            logger.exception("fund_sync_failed", fund_code=fund_code, error=str(e))
            return "failed"
        finally:
            await cache_service.release_lock(lock_key)

    async def sync_funds_bounded(self, fund_codes: list[str], concurrency: int = 5) -> dict[str, int]:
        """Sync many funds with bounded concurrency (MVP spec 7.7).

        Args:
            fund_codes: Fund codes to sync.
            concurrency: Maximum simultaneous provider calls.

        Returns:
            A summary dict: total / written / skipped / failed counts.
        """
        semaphore = asyncio.Semaphore(min(concurrency, 10))

        async def _bounded_sync(code: str) -> str:
            async with semaphore:
                return await self.sync_fund(code)

        results = await asyncio.gather(*[_bounded_sync(code) for code in fund_codes])
        summary = {
            "total": len(fund_codes),
            "written": sum(1 for status in results if status == "written"),
            "skipped": sum(1 for status in results if status == "skipped"),
            "failed": sum(1 for status in results if status == "failed"),
        }
        logger.info("fund_batch_sync_completed", **summary)
        return summary

    async def sync_hot_funds(self) -> dict[str, int]:
        """Sync all Hot Funds (held or watchlisted by any user)."""
        codes = await fund_repository.get_hot_fund_codes()
        if not codes:
            logger.info("fund_hot_sync_no_targets")
            return {"total": 0, "written": 0, "skipped": 0, "failed": 0}
        return await self.sync_funds_bounded(codes)

    async def enqueue_sync(self, fund_code: str) -> str:
        """Record a job and hand the sync to the queue; never blocks the caller.

        Args:
            fund_code: The 6-digit fund code to refresh.

        Returns:
            The job ledger id, so the caller can report or trace the attempt.
        """
        job = await job_repository.create("FUND_SYNC", subject=fund_code)
        await enqueue(FUND_SYNC_TASK, fund_code=fund_code, job_id=job.id)
        logger.info("fund_sync_enqueued", fund_code=fund_code, job_id=job.id)
        return job.id

    async def is_nav_stale(self, fund_code: str) -> bool:
        """True when the latest stored NAV is older than the staleness budget."""
        latest = await fund_repository.get_latest_nav(fund_code)
        if latest is None:
            return True
        cutoff = utc_now() - timedelta(hours=settings.FUND_NAV_STALE_HOURS)
        # A row without fetched_at only carries a business date: compare against
        # that day's market close in UTC, not midnight local.
        fetched = latest.fetched_at or business_close_utc(latest.nav_date)
        return fetched < cutoff


fund_sync_service = FundSyncService()
