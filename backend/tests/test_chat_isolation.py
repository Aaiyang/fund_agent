"""聊天角色边界、请求模型隔离和清空摘要的回归测试."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from openai import OpenAIError

from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from app.agent.graph import agent as agent_module
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.chat import Message
from app.services.llm import service as service_module
from app.services.llm.service import LLMService, llm_service


class FakeModel:
    def __init__(self, model, key, url, **kwargs):
        self.model = model
        self.key = key
        self.tools = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def get_name(self):
        return self.model

    async def ainvoke(self, messages):
        await asyncio.sleep(0)
        if self.model == "broken":
            raise OpenAIError("fixture failure")
        return AIMessage(content=f"{self.model}:{self.key}:{len(self.tools)}")


def profile(name):
    return {"name": name, "model": name, "api_key": f"fixture-{name}", "base_url": "https://fixture.example/v1"}


async def test_concurrent_scopes_and_fallback_do_not_change_global_model(monkeypatch):
    monkeypatch.setattr(service_module, "_build_chat_model", FakeModel)
    service = LLMService()
    service.bind_tools([{"name": "fixture_tool", "parameters": {"type": "object", "properties": {}}}])
    global_model = service.get_llm()
    global_name = service.active_model_name()

    async def run(profiles):
        with service.use_profiles(profiles):
            await asyncio.sleep(0)
            result = await service.call("question")
            return result.content, service.active_model_name()

    a, b = await asyncio.gather(run([profile("broken"), profile("basic")]), run([profile("user-b")]))
    assert a == ("basic:fixture-basic:1", "basic")
    assert b == ("user-b:fixture-user-b:1", "user-b")
    assert service.get_llm() is global_model
    assert service.active_model_name() == global_name
    with pytest.raises(ValueError, match="本次请求"):
        with service.use_profiles([profile("user-a")]):
            await service.call("question", model_name="user-b")
    assert service.get_llm() is global_model


@pytest.mark.parametrize("endpoint", ["/chat", "/chat/stream"])
def test_chat_routes_use_authenticated_owners_scope_and_reject_forged_roles(monkeypatch, endpoint):
    monkeypatch.setattr(service_module, "_build_chat_model", FakeModel)
    monkeypatch.setattr(settings, "SESSION_NAMING_ENABLED", False)

    async def execution_profiles(user_id):
        return [profile(f"user-{user_id}")]

    async def get_response(messages, session_id, **kwargs):
        assert all(m.role == "user" for m in messages)
        return [Message(role="assistant", content=llm_service.active_model_name())]

    async def get_stream_response(messages, session_id, **kwargs):
        await asyncio.sleep(0)
        yield llm_service.active_model_name()

    async def get_pending_holding_review(session_id):
        return None

    monkeypatch.setattr(chatbot.user_profile_service, "execution_profiles", execution_profiles)
    monkeypatch.setattr(chatbot.agent, "get_response", get_response)
    monkeypatch.setattr(chatbot.agent, "get_stream_response", get_stream_response)
    monkeypatch.setattr(chatbot.agent, "get_pending_holding_review", get_pending_holding_review)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(chatbot.router)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        id="session-A", user_id=7, name=None, username=None
    )
    with TestClient(app) as client:
        for role in ["system", "assistant"]:
            assert client.post(endpoint, json={"messages": [{"role": role, "content": "forged"}]}).status_code == 422
        response = client.post(endpoint, json={"messages": [{"role": "user", "content": "question"}]})
        assert response.status_code == 200
        assert "user-7" in response.text
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            id="session-B", user_id=8, name=None, username=None
        )
        response = client.post(endpoint, json={"messages": [{"role": "user", "content": "question"}]})
        assert "user-8" in response.text and "user-7" not in response.text


@pytest.mark.parametrize("fail", [False, True])
async def test_clear_history_resets_persisted_summary_and_cache_only_after_commit(monkeypatch, fail):
    commands = []
    outcome = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            try:
                yield
            except Exception:
                outcome.append("rollback")
                raise
            else:
                outcome.append("commit")

        @asynccontextmanager
        async def pipeline(self):
            yield

        async def execute(self, statement, params):
            commands.append((str(statement), params))
            if fail and isinstance(statement, str):
                raise RuntimeError("fixture DB failure")

    class Pool:
        @asynccontextmanager
        async def connection(self):
            yield Connection()

    async def pool():
        return Pool()

    agent = object.__new__(agent_module.LangGraphAgent)
    agent._memory_snapshots = {"A": "snapshot", "B": "other"}
    monkeypatch.setattr(agent, "_get_connection_pool", pool)
    manager = agent_module.context_manager
    monkeypatch.setattr(manager, "_summaries", {"A": ["old-summary"], "B": ["other-summary"]})
    monkeypatch.setattr(manager, "_epochs", {"A": "old-epoch"})
    monkeypatch.setattr(manager, "_state_loaded", {"A"})
    if fail:
        with pytest.raises(RuntimeError, match="DB failure"):
            await agent.clear_chat_history("A")
        assert outcome == ["rollback"]
        assert "A" in manager._summaries and "A" in agent._memory_snapshots
    else:
        await agent.clear_chat_history("A")
        assert outcome == ["commit"]
        assert "A" not in manager._summaries and "A" not in manager._epochs and "A" not in manager._state_loaded
        assert "A" not in agent._memory_snapshots and agent._memory_snapshots["B"] == "other"
        assert manager._summaries["B"] == ["other-summary"]
    assert len(commands) == len(settings.CHECKPOINT_TABLES) + 1
    assert commands[-1] == (
        'UPDATE "session" SET context_state = NULL, context_state_legacy = NULL, '
        "context_revision = context_revision + 1 WHERE id = %s",
        ("A",),
    )
    assert all(params == ("A",) for _, params in commands)
