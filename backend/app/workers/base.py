"""Shared execution wrapper for Taskiq workers: bounded retries + PG audit.

Every durable background task runs through :func:`run_job` so failures carry an
error code, attempt count and timestamps into PostgreSQL instead of living only
in logs (MVP spec 7.8, and 7.4 rule 3: retryable work must be durable).
"""

from collections.abc import Awaitable, Callable

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import logger
from app.repositories.job_repository import job_repository


async def run_job(
    job_id: str,
    work: Callable[[], Awaitable[None]],
    on_failure: Callable[[Exception], Awaitable[None]] | None = None,
) -> str:
    """Run `work` with a bounded retry budget, recording the outcome.

    Args:
        job_id: Ledger row created before the task was enqueued.
        work: Coroutine performing the actual task.
        on_failure: Optional business hook (e.g. mark an import failed).

    Returns:
        "ok" or "failed". Never raises: a recorded failure must not be
        redelivered by the broker forever.
    """
    await job_repository.mark_running(job_id)
    attempts = max(settings.BACKGROUND_TASK_MAX_ATTEMPTS, 1)

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    logger.warning(
                        "background_job_retrying",
                        job_id=job_id,
                        attempt=attempt.retry_state.attempt_number,
                    )
                await work()
    except Exception as e:
        logger.exception("background_job_failed", job_id=job_id, error=str(e))
        await job_repository.finish(job_id, "FAILED", error_code=type(e).__name__, error_message=str(e))
        if on_failure is not None:
            await on_failure(e)
        return "failed"

    await job_repository.finish(job_id, "SUCCEEDED")
    logger.info("background_job_succeeded", job_id=job_id)
    return "ok"
