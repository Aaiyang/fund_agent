"""Fund sync worker tasks.

Run a dedicated worker with:
    taskiq worker app.core.task_queue:broker app.workers.fund_sync app.workers.screenshot_import
Without Redis the broker falls back to in-process execution (see
app.core.task_queue); task state remains authoritative in PostgreSQL.
"""

from app.core.logging import logger
from app.core.task_queue import broker
from app.repositories.job_repository import job_repository
from app.services.fund_sync_service import fund_sync_service
from app.workers.base import run_job


@broker.task
async def sync_fund_task(fund_code: str, job_id: str | None = None) -> str:
    """Sync one fund's master data and NAV history.

    Args:
        fund_code: The 6-digit fund code.
        job_id: Ledger row created by the caller; one is created here when the
            task is triggered directly (e.g. by an external scheduler).

    Returns:
        "ok" or "failed".
    """
    if job_id is None:
        job = await job_repository.create("FUND_SYNC", subject=fund_code)
        job_id = job.id

    async def _work() -> None:
        status = await fund_sync_service.sync_fund(fund_code)
        if status == "failed":
            raise RuntimeError("fund_sync_failed")

    return await run_job(job_id, _work)


@broker.task
async def sync_hot_funds_task(job_id: str | None = None) -> str:
    """Sync every Hot Fund (held or watchlisted) in one bounded sweep.

    Args:
        job_id: Ledger row created by the caller, when there is one.

    Returns:
        "ok" or "failed".
    """
    if job_id is None:
        job = await job_repository.create("HOT_FUND_SYNC")
        job_id = job.id

    async def _work() -> None:
        summary = await fund_sync_service.sync_hot_funds()
        logger.info("hot_fund_sync_sweep", **summary)

    return await run_job(job_id, _work)
