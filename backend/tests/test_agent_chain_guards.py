"""链路防护回归：中断兜底、重复守卫的轮次窗口、整轮时限.

对应审查里确认过的三个失败模式：``state.next`` 有值但当前任务没有中断时裸取
``tasks[0].interrupts[0]`` 会 IndexError 变成 500；同参数计数跨用户轮累计会让一
句正常的重复提问在长会话里被永久拒绝；主入口没有整轮时限时会话锁与连接可以被
一轮跑上几十分钟。
"""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import StateSnapshot

from app.agent.graph.agent import LangGraphAgent
from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from app.core import session_lock
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas import Message

_FIXTURE_PROFILES = [
    {
        "name": "fixture",
        "model": "fixture",
        "api_key": "fixture",  # pragma: allowlist secret
        "base_url": "https://fixture.invalid/v1",
    }
]


def _as_log_entry(message) -> dict:
    """把消息统一成可断言的字典：prepare 之后传进来的已是真实 BaseMessage 对象."""
    if isinstance(message, dict):
        return {"type": message.get("type"), "content": str(message.get("content", ""))}
    return {"type": getattr(message, "type", None), "content": str(getattr(message, "content", ""))}


def _tool_call(call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "counted_tool", "args": {"fund_code": "000001"}, "id": call_id, "type": "tool_call"}],
    )


class _ScriptedLLM:
    def __init__(self, script: list[AIMessage]) -> None:
        self.script = list(script)
        self.prompts: list[list] = []

    def get_llm(self):
        return None

    async def call(self, messages, *args, **kwargs):
        self.prompts.append([_as_log_entry(m) for m in messages])
        return self.script.pop(0)


class _CountingTool:
    name = "counted_tool"

    def __init__(self) -> None:
        self.executed = 0

    async def ainvoke(self, args):
        self.executed += 1
        return "[TOOL_OK]\n{}"


def _build_agent(monkeypatch, script: list[AIMessage], tool: _CountingTool) -> tuple[LangGraphAgent, _ScriptedLLM]:
    agent = LangGraphAgent()
    llm = _ScriptedLLM(script)
    monkeypatch.setattr(agent, "llm_service", llm)
    monkeypatch.setattr(agent, "tools_by_name", {"counted_tool": tool})
    agent._graph = agent._build_graph(InMemorySaver())
    return agent, llm


def test_pending_interrupt_value_falls_back_when_no_interrupts() -> None:
    # 崩溃/断连遗留的挂起节点让 state.next 有值，但任务里没有 interrupts。
    def state_with(tasks: list) -> StateSnapshot:
        return cast("StateSnapshot", SimpleNamespace(tasks=tasks))

    assert LangGraphAgent._pending_interrupt_value(state_with([SimpleNamespace(interrupts=[])])) == (
        "Waiting for input."
    )
    assert LangGraphAgent._pending_interrupt_value(state_with([])) == "Waiting for input."
    value = {"kind": "holding_import_review"}
    assert LangGraphAgent._pending_interrupt_value(
        state_with([SimpleNamespace(interrupts=[SimpleNamespace(value=value)])])
    ) == (  # noqa: E501
        value
    )


async def test_duplicate_guard_counts_only_within_the_current_turn(monkeypatch) -> None:
    tool = _CountingTool()
    agent, llm = _build_agent(
        monkeypatch,
        [_tool_call("c0"), _tool_call("c1"), _tool_call("c2"), AIMessage(content="第一轮答复")],
        tool,
    )
    await agent.get_response([Message(role="user", content="查净值")], "dup-window", user_id="7")
    # 同一轮里第三次同参数仍然拦得住
    assert tool.executed == 2
    assert any("DUPLICATE_TOOL_CALL" in item["content"] for item in llm.prompts[-1] if item["type"] == "tool")

    # 新用户轮窗口重置：换以前被跨轮累计卡住的工具（get_fund_history 那一类）也要能重查
    second_turn = _ScriptedLLM([_tool_call("c3"), AIMessage(content="第二轮答复")])
    monkeypatch.setattr(agent, "llm_service", second_turn)
    result = await agent.get_response([Message(role="user", content="再查一次净值")], "dup-window", user_id="7")
    assert tool.executed == 3
    assert result[-1] == Message(role="assistant", content="第二轮答复")

    # 只看本轮那次调用的结果：跨轮累计的旧修复会把 c3 直接判成 DUPLICATE_TOOL_CALL
    graph = agent._graph
    assert graph is not None
    state = await graph.aget_state({"configurable": {"thread_id": "dup-window"}})
    latest = next(m for m in reversed(state.values["messages"]) if getattr(m, "tool_call_id", None) == "c3")
    assert latest.content.startswith("[TOOL_OK]")


@pytest.fixture
def slow_chat_app(monkeypatch):
    """把整轮时限压到几十毫秒，让桩 agent 必然超时."""
    monkeypatch.setattr(settings, "AGENT_TURN_TIMEOUT", 0.05)
    monkeypatch.setattr(settings, "SESSION_NAMING_ENABLED", False)
    monkeypatch.setattr(session_lock.database_service, "get_session", AsyncMock(return_value=object()))

    async def hanging(*args, **kwargs):
        await asyncio.sleep(1)
        return []

    stub = SimpleNamespace(
        get_response=hanging,
        get_pending_holding_review=AsyncMock(return_value=None),
        get_run_continuation=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(chatbot, "agent", stub)

    async def profiles(user_id: int) -> list[dict[str, str]]:
        return list(_FIXTURE_PROFILES)

    monkeypatch.setattr(chatbot.user_profile_service, "execution_profiles", profiles)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(chatbot.router)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        id="slow-session", user_id=7, name=None, username=None
    )
    return app


def test_chat_returns_504_when_the_turn_budget_is_exhausted(slow_chat_app) -> None:
    with TestClient(slow_chat_app) as client:
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "分析基金"}]})
    assert response.status_code == 504, response.text
    assert response.json()["detail"] == "chat_turn_timeout_use_continue"


def test_turn_budget_releases_the_session_lock_for_the_next_request(slow_chat_app) -> None:
    # 超时不能把执行锁留在原地：下一次请求必须能立刻拿到会话锁而不是 409
    with TestClient(slow_chat_app) as client:
        assert client.post("/chat", json={"messages": [{"role": "user", "content": "第一次"}]}).status_code == 504
        assert client.post("/chat", json={"messages": [{"role": "user", "content": "第二次"}]}).status_code == 504
