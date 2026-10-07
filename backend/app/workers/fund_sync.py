"""基金同步的后台 worker 任务.

启动独立 worker 进程的命令：
    taskiq worker app.core.task_queue:broker app.workers.fund_sync app.workers.screenshot_import
没有 Redis 时 broker 退化为本进程内执行
（见 app.core.task_queue）；但任务状态的权威记录始终在 PostgreSQL 里。
"""

from app.core.logging import logger
from app.core.task_queue import broker
from app.repositories.job_repository import job_repository
from app.services.fund_sync_service import fund_sync_service
from app.workers.base import run_job


@broker.task
async def sync_fund_task(fund_code: str, job_id: str | None = None) -> str:
    """同步单只基金的基本资料与净值历史.

    Args:
        fund_code: 6 位基金代码。
        job_id: 调用方创建好的账本行；任务被直接触发时（例如由外部调度器触发），
            这里会自己补建一条。

    Returns:
        "ok" 或 "failed"。
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
    """一轮有界的批量同步，覆盖全部热门基金（持仓中的与自选里的）.

    Args:
        job_id: 调用方创建好的账本行，可能没有。

    Returns:
        "ok" 或 "failed"。
    """
    if job_id is None:
        job = await job_repository.create("HOT_FUND_SYNC")
        job_id = job.id

    async def _work() -> None:
        summary = await fund_sync_service.sync_hot_funds()
        logger.info("hot_fund_sync_sweep", **summary)

    return await run_job(job_id, _work)
