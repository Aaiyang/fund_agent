"""Taskiq worker 的共用执行外壳：有限次重试 + PostgreSQL 留痕.

每个持久化后台任务都要走 :func:`run_job`，这样失败会把错误码、尝试次数和
各阶段时间戳一并写进 PostgreSQL，而不只留在日志里
（MVP spec 7.8，以及 7.4 规则 3：可重试的工作必须先做到持久化）。
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
    """在有限重试额度内执行 `work`，并把结果写进任务账本.

    Args:
        job_id: 任务入队之前就创建好的账本行。
        work: 真正执行任务的协程。
        on_failure: 可选的业务侧钩子（例如把导入批次标记为失败）。

    Returns:
        "ok" 或 "failed"。本函数永不抛异常：失败已经记进账本了，
        就不该再让 broker 把它无限重投下去。
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
