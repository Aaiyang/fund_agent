"""截图识别导入的后台 worker 任务（Taskiq）."""

from app.core.task_queue import broker
from app.repositories.job_repository import job_repository
from app.services.holding_import_service import holding_import_service
from app.workers.base import run_job


@broker.task
async def process_screenshot_import_task(import_id: str, user_id: int, job_id: str | None = None) -> str:
    """把用户上传的截图解析成一份待人工核对的草稿.

    正常在 Taskiq worker 里跑（Redis broker）；退化到没有 Redis 时，
    就在本进程的后台跑。批次状态和任务账本都落在 PostgreSQL 里，
    所以 worker 挂掉之后仍然可以恢复。

    Args:
        import_id: HoldingImport 批次的 ID。
        user_id: 批次归属人的 ID，worker 侧据此再校验一次归属。
        job_id: 调用方创建好的账本行，可能没有。

    Returns:
        "ok" 或 "failed"。
    """
    if job_id is None:
        job = await job_repository.create("SCREENSHOT_IMPORT", subject=import_id)
        job_id = job.id

    return await run_job(
        job_id,
        lambda: holding_import_service.process_screenshot_import(import_id, user_id),
        on_failure=lambda error: holding_import_service.mark_failed(import_id, str(error)),
    )
