"""周期后台任务：由 API 进程入队热门基金同步.

执行仍然归 Taskiq worker 负责（无 Redis 时落到进程内 broker 兜底），
这个循环只入队，所以请求链路上绝不会去做数据源 I/O（MVP spec 7.13）。
外部调度器直接驱动 ``sync_hot_funds_task`` 时，
用 FUND_HOT_SYNC_ENABLED=false 把这里关掉。
"""

import asyncio
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.core.task_queue import enqueue
from app.services.memory import memory_service
from app.workers import HOT_FUND_SYNC_TASK

_job: asyncio.Task[Any] | None = None
_memory_job: asyncio.Task[Any] | None = None


async def _memory_recovery_loop() -> None:
    """立即及定期恢复漏投递/租期过期任务，不依赖热门基金同步开关."""
    while True:
        try:
            for user_id in await memory_service.repository.ready_users():
                await memory_service.dispatch(user_id)
        except Exception:
            logger.exception("memory_recovery_dispatch_failed")
        await asyncio.sleep(settings.MEMORY_RECOVERY_INTERVAL_SECONDS)


async def _hot_fund_loop() -> None:
    """睡满一个周期后入队一轮热门基金同步，直到被取消."""
    interval_minutes = settings.FUND_HOT_SYNC_INTERVAL_MINUTES
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await enqueue(HOT_FUND_SYNC_TASK)
            logger.info("hot_fund_sync_enqueued", interval_minutes=interval_minutes)
        except Exception as e:
            logger.warning("hot_fund_sync_enqueue_failed", error=str(e))


def start_periodic_jobs() -> None:
    """开关打开时启动周期入队循环."""
    global _job, _memory_job
    if settings.LONG_TERM_MEMORY_ENABLED and _memory_job is None:
        _memory_job = asyncio.create_task(_memory_recovery_loop(), name="memory_recovery_loop")
    if not settings.FUND_HOT_SYNC_ENABLED:
        logger.info("periodic_jobs_disabled")
        return
    if _job is None:
        _job = asyncio.create_task(_hot_fund_loop(), name="hot_fund_sync_loop")
        logger.info("periodic_jobs_started", interval_minutes=settings.FUND_HOT_SYNC_INTERVAL_MINUTES)


async def stop_periodic_jobs() -> None:
    """取消周期循环，并等它真正退出."""
    global _job, _memory_job
    if _memory_job is not None:
        _memory_job.cancel()
        try:
            await _memory_job
        except asyncio.CancelledError:
            pass
        _memory_job = None
    if _job is not None:
        _job.cancel()
        try:
            await _job
        except asyncio.CancelledError:
            pass
        _job = None
        logger.info("periodic_jobs_stopped")
