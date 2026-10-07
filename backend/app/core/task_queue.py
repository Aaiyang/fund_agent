"""Taskiq broker 与入队辅助函数.

可靠路径是 Taskiq + Redis broker，配一个独立的 worker 进程
（`taskiq worker app.core.task_queue:broker`）。没配 Redis 时走退化路径：
InMemoryBroker 在本进程的事件循环后台执行任务 —— 无论走哪条，任务状态都以
PostgreSQL 里的记录为准。
"""

from typing import Any

from app.core.config import settings
from app.core.logging import logger


def _resolve_redis_url() -> str:
    """推导 broker 的 Redis URL：优先用 TASKIQ_REDIS_URL，否则由 Valkey 配置拼出."""
    if settings.TASKIQ_REDIS_URL:
        return settings.TASKIQ_REDIS_URL
    password_part = f":{settings.VALKEY_PASSWORD}@" if settings.VALKEY_PASSWORD else ""
    return f"redis://{password_part}{settings.VALKEY_HOST}:{settings.VALKEY_PORT}/{settings.VALKEY_DB}"


def _create_broker() -> Any:
    """按配置创建 Taskiq broker.

    Returns:
        Taskiq broker 实例：配了 Redis 就用 Redis 后端，否则用进程内实现。
    """
    if not settings.VALKEY_HOST and not settings.TASKIQ_REDIS_URL:
        from taskiq import InMemoryBroker

        logger.info("task_broker_in_memory_fallback", reason="redis_not_configured")
        return InMemoryBroker()

    try:
        from taskiq_redis import ListQueueBroker

        logger.info("task_broker_redis", url=_resolve_redis_url())
        return ListQueueBroker(url=_resolve_redis_url())
    except ImportError:
        from taskiq import InMemoryBroker

        logger.warning("task_broker_in_memory_fallback", reason="taskiq_redis_not_installed")
        return InMemoryBroker()


broker = _create_broker()


async def enqueue(task_name: str, **kwargs: Any) -> None:
    """按任务名把任务交给 broker.

    刻意用名字而不是直接 import：worker 模块会去 import 那些负责给它入队的服务，
    反向再 import 一次就闭环成循环依赖。任务模块在启动时被导入（见 app.main），
    以此填充 broker 的任务注册表。

    Args:
        task_name: Taskiq 注册时使用的任务 id，例如
            "app.workers.fund_sync:sync_fund_task"。
        **kwargs: 任务参数。

    Raises:
        RuntimeError: 本进程从未注册过这个任务。
    """
    task = broker.find_task(task_name)
    if task is None:
        raise RuntimeError(f"task_not_registered_{task_name}")
    await task.kiq(**kwargs)


async def startup_broker() -> None:
    """为当前进程（API 或 worker）初始化 broker."""
    await broker.startup()


async def shutdown_broker() -> None:
    """释放当前进程的 broker 资源."""
    await broker.shutdown()
