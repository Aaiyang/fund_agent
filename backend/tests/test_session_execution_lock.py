"""删除、清空、旧鉴权请求和取消共用会话执行边界."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api.v1 import auth, chatbot
from app.core import session_lock
from app.core.cache import InMemoryCacheService, cache_key
from app.core.limiter import limiter


@pytest.fixture
def protected_session(monkeypatch):
    cache = InMemoryCacheService()
    identity = SimpleNamespace(id="lock-session", user_id=7)
    monkeypatch.setattr(session_lock, "cache_service", cache)
    monkeypatch.setattr(chatbot, "cache_service", cache)
    monkeypatch.setattr(session_lock.database_service, "get_session", AsyncMock(return_value=identity))
    monkeypatch.setattr(limiter, "enabled", False)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(chatbot.router, prefix="/chatbot")
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[auth.get_current_session] = lambda: identity
    return app, identity, cache


@pytest.mark.parametrize("path", ["/chatbot/messages", "/auth/session/lock-session"])
async def test_clear_and_delete_refuse_active_chat(protected_session, monkeypatch, path):
    app, identity, cache = protected_session
    clear = AsyncMock()
    delete = AsyncMock()
    monkeypatch.setattr(chatbot.agent, "clear_chat_history", clear)
    monkeypatch.setattr(auth.db_service, "delete_session", delete)
    async with session_lock.session_execution_guard(identity.id):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(path)
        assert response.status_code == 409, response.text
    clear.assert_not_awaited()
    delete.assert_not_awaited()


async def test_deleted_session_cannot_start_after_earlier_authentication(protected_session, monkeypatch):
    _, identity, cache = protected_session
    monkeypatch.setattr(session_lock.database_service, "get_session", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as error:
        async with session_lock.session_execution_guard(identity.id):
            pytest.fail("deleted session executed")
    assert error.value.status_code == 404
    assert await cache.acquire_lock(cache_key("agent:holding-decision", identity.id)) is not None


async def test_cancelled_execution_releases_its_own_lease(protected_session):
    _, identity, cache = protected_session
    entered = asyncio.Event()

    async def run():
        async with session_lock.session_execution_guard(identity.id):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await cache.acquire_lock(cache_key("agent:holding-decision", identity.id)) is not None
