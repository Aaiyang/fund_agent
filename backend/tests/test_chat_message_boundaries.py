"""验证长回答通过真实检查点与 HTTP 返回，输入边界仍由请求模型守住."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.graph.agent import LangGraphAgent
from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from unittest.mock import AsyncMock

from app.core import session_lock
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.chat import ChatInputMessage, ChatResponse, Message
from app.schemas.graph import GraphState


LONG_ANSWER = "基金分析📈：走势、成本与风险。\n" * 6000 + '\n```fund-chart\n{"data":[]}\n```\n完整结尾'


class AnswerModel(FakeMessagesListChatModel):
    async def _astream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        yield ChatGenerationChunk(message=AIMessageChunk(content=LONG_ANSWER))


@pytest.fixture
def chat_app(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_NAMING_ENABLED", False)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    model = AnswerModel(responses=[AIMessage(content=LONG_ANSWER)])

    async def answer(state: GraphState) -> dict[str, Any]:
        return {"messages": [await model.ainvoke(state.messages, stream=True)]}

    graph = StateGraph(GraphState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    agent = object.__new__(LangGraphAgent)
    agent.llm_service = chatbot.llm_service
    agent._graph = graph.compile(checkpointer=InMemorySaver())
    monkeypatch.setattr(session_lock.database_service, "get_session", AsyncMock(return_value=object()))
    monkeypatch.setattr(chatbot, "agent", agent)

    async def profiles(user_id: int) -> list[dict[str, str]]:
        return [
            {
                "name": "fixture",
                "model": "fixture",
                "api_key": "fixture",  # pragma: allowlist secret
                "base_url": "https://fixture.invalid/v1",
            }
        ]

    monkeypatch.setattr(chatbot.user_profile_service, "execution_profiles", profiles)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(chatbot.router)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        id="long-answer-session", user_id=7, name=None, username=None
    )
    return app, agent


def test_long_response_is_returned_and_checkpoint_history_reloads_without_truncation(chat_app):
    app, _agent = chat_app
    with TestClient(app) as client:
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "分析基金"}]})
        assert response.status_code == 200, response.text
        messages = response.json()["messages"]
        assert messages[-1]["content"] == LONG_ANSWER
        history = client.get("/messages")
        assert history.status_code == 200, history.text
        assert history.json()["messages"] == messages


def test_streamed_long_response_is_complete_and_can_reload_from_history(chat_app):
    app, _agent = chat_app
    with TestClient(app) as client:
        response = client.post("/chat/stream", json={"messages": [{"role": "user", "content": "分析基金"}]})
        assert response.status_code == 200
        frames = [
            json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert "".join(frame["content"] for frame in frames if not frame["done"]) == LONG_ANSWER
        assert frames[-1]["done"] and frames[-1]["content"] == ""
        history = client.get("/messages")
        assert history.status_code == 200
        assert history.json()["messages"][-1]["content"] == LONG_ANSWER


async def test_existing_long_history_is_readable_without_rewriting_checkpoint(chat_app):
    _app, agent = chat_app
    config = {"configurable": {"thread_id": "legacy-history"}}
    legacy_user = "历史用户正文" * 1000
    answer = LONG_ANSWER + "\n```html\n<script>example()</script>\n```\n\0"
    await agent._graph.aupdate_state(
        config, {"messages": [HumanMessage(content=legacy_user), AIMessage(content=answer)]}
    )
    before = await agent._graph.aget_state(config)
    history = await agent.get_chat_history("legacy-history")
    assert [message.content for message in history] == [legacy_user, answer]
    after = await agent._graph.aget_state(config)
    assert after.config == before.config and after.values == before.values


@pytest.mark.parametrize("endpoint", ["/chat", "/chat/stream"])
def test_input_length_boundary_still_enforced_by_http_request(chat_app, endpoint):
    app, _agent = chat_app
    with TestClient(app) as client:
        accepted = client.post(endpoint, json={"messages": [{"role": "user", "content": "问" * 3000}]})
        assert accepted.status_code == 200
        rejected = client.post(endpoint, json={"messages": [{"role": "user", "content": "问" * 3001}]})
        assert rejected.status_code == 422
        assert rejected.json()["detail"][0]["type"] == "string_too_long"


@pytest.mark.parametrize("endpoint", ["/chat", "/chat/stream"])
@pytest.mark.parametrize("content", ["", "<script>alert(1)</script>", "输入\0正文"])
def test_invalid_input_still_rejected(chat_app, endpoint, content):
    app, _agent = chat_app
    with TestClient(app) as client:
        response = client.post(endpoint, json={"messages": [{"role": "user", "content": content}]})
    assert response.status_code == 422


def test_output_schema_has_no_input_length_limit():
    assert ChatInputMessage.model_json_schema()["properties"]["content"]["maxLength"] == 3000
    assert "maxLength" not in Message.model_json_schema()["properties"]["content"]
    response = ChatResponse(messages=[Message(role="assistant", content=LONG_ANSWER)])
    assert json.loads(response.model_dump_json())["messages"][0]["content"] == LONG_ANSWER
