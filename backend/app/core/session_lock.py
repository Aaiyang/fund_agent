"""聊天、人工恢复与会话删除共享的执行边界."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException

from app.core.cache import InMemoryCacheService, ValkeyCacheService, cache_key, cache_service
from app.core.config import settings
from app.services.database import database_service


async def ensure_session_exists(session_id: str) -> None:
    """取得锁后重新校验，拒绝鉴权之后已被删除的会话."""
    if await database_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session_not_found")


@asynccontextmanager
async def session_execution_guard(
    session_id: str, *, cache: InMemoryCacheService | ValkeyCacheService | None = None
) -> AsyncIterator[None]:
    """同一会话的执行与删除互斥，并在 lease 到期前终止本次执行."""
    cache = cache if cache is not None else cache_service
    ttl = max(600, settings.LLM_TOTAL_TIMEOUT * 30)
    lease = await cache.acquire_lock(cache_key("agent:holding-decision", session_id), ttl=ttl, fail_open=False)
    if lease is None:
        raise HTTPException(status_code=409, detail="agent_decision_in_progress")
    try:
        async with asyncio.timeout(ttl - 120):
            await ensure_session_exists(session_id)
            yield
    finally:
        await asyncio.shield(cache.release_lock(lease))
