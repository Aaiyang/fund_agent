"""Fund sync worker tasks.

Run a dedicated worker with:
    taskiq worker app.workers.fund_sync:broker
Without Redis the broker falls back to in-process execution (see
app.core.task_queue); task state remains authoritative in PostgreSQL.
"""

from app.core.task_queue import broker
from app.services.fund_sync_service import fund_sync_service


@broker.task
async def sync_fund_task(fund_code: str) -> bool:
    """Sync one fund's master data and NAV history."""
    return await fund_sync_service.sync_fund(fund_code)


@broker.task
async def sync_hot_funds_task() -> dict[str, int]:
    """Sync every Hot Fund (held or watchlisted)."""
    return await fund_sync_service.sync_hot_funds()
