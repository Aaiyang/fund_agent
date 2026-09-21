"""Periodic background jobs: enqueue Hot Fund sync from the API process.

Execution still belongs to the Taskiq worker (or the in-process broker
fallback) — this loop only enqueues, so the request path never performs
provider I/O (MVP spec 7.13). Disable with FUND_HOT_SYNC_ENABLED=false when an
external scheduler drives ``sync_hot_funds_task`` instead.
"""

import asyncio
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.core.task_queue import enqueue
from app.workers import HOT_FUND_SYNC_TASK

_job: asyncio.Task[Any] | None = None


async def _hot_fund_loop() -> None:
    """Sleep, then enqueue one Hot Fund sweep, until cancelled."""
    interval_minutes = settings.FUND_HOT_SYNC_INTERVAL_MINUTES
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await enqueue(HOT_FUND_SYNC_TASK)
            logger.info("hot_fund_sync_enqueued", interval_minutes=interval_minutes)
        except Exception as e:
            logger.warning("hot_fund_sync_enqueue_failed", error=str(e))


def start_periodic_jobs() -> None:
    """Start the periodic enqueue loop when enabled."""
    global _job
    if not settings.FUND_HOT_SYNC_ENABLED:
        logger.info("periodic_jobs_disabled")
        return
    if _job is None:
        _job = asyncio.create_task(_hot_fund_loop(), name="hot_fund_sync_loop")
        logger.info("periodic_jobs_started", interval_minutes=settings.FUND_HOT_SYNC_INTERVAL_MINUTES)


async def stop_periodic_jobs() -> None:
    """Cancel the periodic loop and wait for it to unwind."""
    global _job
    if _job is not None:
        _job.cancel()
        try:
            await _job
        except asyncio.CancelledError:
            pass
        _job = None
        logger.info("periodic_jobs_stopped")
