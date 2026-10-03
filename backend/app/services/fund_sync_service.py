"""Fund sync orchestration: lock-guarded, idempotent external data sync."""

import asyncio
from datetime import timedelta

from app.core.cache import cache_key, cache_service
from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import fund_sync_total
from app.core.task_queue import enqueue
from app.integrations.fund_data.akshare_client import AKSHARE_AVAILABLE
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.integrations.fund_data.models import FundExternalNav
from app.models.fund import Fund
from app.repositories.fund_repository import fund_repository, fund_write_repository
from app.repositories.job_repository import job_repository
from app.schemas.fund import FundNavRefreshResponse
from app.utils.clock import business_close_utc, business_today, utc_now
from app.workers import FUND_SYNC_TASK

# The batched quote table carries no row for some funds (whole companies are
# absent from it), so those fall back to the per-fund sync — which costs three
# upstream calls and is therefore requested at most once per fund per day.
_MISSING_NAV_SYNC_COOLDOWN_SECONDS = 24 * 3600


def plan_nav_writes(
    codes: list[str], navs: list[FundExternalNav], funds: dict[str, Fund]
) -> tuple[list[FundExternalNav], list[str]]:
    """Split a batched quote payload into rows to write and codes to chase.

    Two things must not be written: a code the caller did not ask for (the source
    table covers every fund), and a code with no master row — `fund_nav` has a
    foreign key onto `fund`, so one orphan would fail the whole chunked upsert
    and cost the caller every other update in the batch. Both land in `missing`
    and get the per-fund sync, which creates the master row first.
    """
    wanted = set(codes)
    newest: dict[str, FundExternalNav] = {}
    for nav in navs:
        if nav.fund_code not in wanted:
            continue
        current = newest.get(nav.fund_code)
        if current is None or nav.nav_date > current.nav_date:
            newest[nav.fund_code] = nav
    writable = [nav for code, nav in sorted(newest.items()) if code in funds]
    missing = sorted(code for code in wanted if code not in newest or code not in funds)
    return writable, missing


class FundSyncService:
    """Syncs one or many funds from the external provider into PostgreSQL.

    Deduplication: a distributed lock keyed by ``fund_sync:{fund_code}:{date}``
    keeps two workers from syncing the same fund at the same moment. It is
    released on the way out, so it is a mutex rather than a once-a-day gate:
    re-syncing a fund deliberately refetches. Upserts make retries idempotent —
    re-running never duplicates rows.
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

    async def refresh_user_latest_navs(self, user_id: int) -> FundNavRefreshResponse:
        """Refresh the latest NAV of every fund this user holds or watchlists.

        One batched source table answers the whole set, where the per-fund path
        would cost three calls each — this is what makes it cheap enough to run
        when the holdings screen opens. Written rows land in PostgreSQL before
        the call returns, so the caller can re-read the lists immediately.
        """
        codes = await fund_repository.list_user_fund_codes(user_id)
        if not codes:
            return FundNavRefreshResponse()
        if not AKSHARE_AVAILABLE:
            # The provider returns an empty list without the dependency, which
            # would be reported as "every fund is missing" unless gated here.
            logger.warning("fund_nav_refresh_unavailable", user_id=user_id, count=len(codes))
            return FundNavRefreshResponse(requested=len(codes), status="unavailable")
        if not await cache_service.acquire_lock(
            cache_key("nav_refresh_user", str(user_id)), ttl=settings.FUND_NAV_REFRESH_COOLDOWN_SECONDS
        ):
            # A cooldown, not a mutex: never released, so a tab-switching user
            # cannot stack one 20k-row fetch per focus.
            logger.debug("fund_nav_refresh_throttled", user_id=user_id, count=len(codes))
            return FundNavRefreshResponse(requested=len(codes), status="throttled")

        try:
            navs = await asyncio.wait_for(
                akshare_fund_provider.get_latest_navs(codes, force=True),
                timeout=settings.FUND_NAV_REFRESH_TIMEOUT_SECONDS,
            )
        except Exception as e:
            # The fetch continues in its executor thread and fills the source
            # cache, so the next attempt is cheap. Old numbers stay on screen.
            logger.exception("fund_nav_refresh_failed", user_id=user_id, count=len(codes), error=str(e))
            return FundNavRefreshResponse(requested=len(codes), status="deferred")

        writable, missing = plan_nav_writes(codes, navs, await fund_repository.get_funds(codes))
        if writable:
            await fund_write_repository.upsert_navs(writable)
            for nav in writable:
                # The lists read PostgreSQL, but the detail page caches this key:
                # without the delete it would serve the pre-refresh NAV.
                await cache_service.delete(cache_key("fund_latest_nav", nav.fund_code))
        for code in missing:
            await self._queue_missing_nav_refresh(code)

        logger.info(
            "fund_nav_refresh_completed",
            user_id=user_id,
            requested=len(codes),
            updated=len(writable),
            missing=len(missing),
        )
        return FundNavRefreshResponse(
            status="ok" if not missing else "partial",
            requested=len(codes),
            updated=len(writable),
            missing=missing,
            nav_date=max((nav.nav_date for nav in writable), default=None),
        )

    async def _queue_missing_nav_refresh(self, fund_code: str) -> None:
        """Ask for one fund the batched table did not carry.

        Absent from that table is not "nothing to refresh" — some funds are
        simply never listed in it — so the per-fund sync takes over. It is
        requested once per fund per day because that path is three calls.
        """
        acquired = await cache_service.acquire_lock(
            cache_key("nav_refresh_missing", fund_code), ttl=_MISSING_NAV_SYNC_COOLDOWN_SECONDS
        )
        if not acquired:
            return
        try:
            await self.enqueue_sync(fund_code)
        except Exception as e:
            # A queue outage costs one fund's numbers, not the whole refresh.
            logger.warning("fund_nav_refresh_fallback_failed", fund_code=fund_code, error=str(e))

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
