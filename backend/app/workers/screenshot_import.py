"""Screenshot import worker task (Taskiq)."""

from app.core.task_queue import broker
from app.repositories.job_repository import job_repository
from app.services.holding_import_service import holding_import_service
from app.workers.base import run_job


@broker.task
async def process_screenshot_import_task(import_id: str, user_id: int, job_id: str | None = None) -> str:
    """Parse uploaded screenshots into a review-ready draft.

    Runs in the Taskiq worker (Redis broker) or, in the degraded no-Redis
    fallback, in-process in the background. Both the batch status and the job
    ledger live in PostgreSQL, so a lost worker is recoverable.

    Args:
        import_id: HoldingImport batch id.
        user_id: Owner id, used to re-check the batch on the worker side.
        job_id: Ledger row created by the caller, when there is one.

    Returns:
        "ok" or "failed".
    """
    if job_id is None:
        job = await job_repository.create("SCREENSHOT_IMPORT", subject=import_id)
        job_id = job.id

    return await run_job(
        job_id,
        lambda: holding_import_service.process_screenshot_import(import_id, user_id),
        on_failure=lambda error: holding_import_service.mark_failed(import_id, str(error)),
    )
