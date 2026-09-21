"""Taskiq broker and enqueue helpers.

Reliable path: Taskiq + Redis broker with a dedicated worker process
(`taskiq worker app.core.task_queue:broker`). Degraded fallback (no Redis
configured): InMemoryBroker executes tasks in-process in the background of
the event loop — task state stays authoritative in PostgreSQL either way.
"""

from typing import Any

from app.core.config import settings
from app.core.logging import logger


def _resolve_redis_url() -> str:
    """Resolve the broker Redis URL from dedicated or Valkey settings."""
    if settings.TASKIQ_REDIS_URL:
        return settings.TASKIQ_REDIS_URL
    password_part = f":{settings.VALKEY_PASSWORD}@" if settings.VALKEY_PASSWORD else ""
    return f"redis://{password_part}{settings.VALKEY_HOST}:{settings.VALKEY_PORT}/{settings.VALKEY_DB}"


def _create_broker() -> Any:
    """Create the Taskiq broker based on configuration.

    Returns:
        A Taskiq broker instance (Redis-backed when configured, else in-memory).
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


async def startup_broker() -> None:
    """Initialize the broker for the current process (API or worker)."""
    await broker.startup()


async def shutdown_broker() -> None:
    """Release broker resources for the current process."""
    await broker.shutdown()
