"""真实图中断与会话 API：名称歧义、恢复、取消及安全边界."""

import json
import asyncio
from types import SimpleNamespace
from typing import Annotated, TypedDict
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from app.agent.graph import fund_selection as selection_module
from app.agent.graph.agent import LangGraphAgent
from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from app.core.cache import InMemoryCacheService
from app.core import session_lock
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.chat import Message
from app.schemas.fund_selection import FundSelectionAction, FundSelectionDecision, FundSelectionResult
from app.schemas.graph import GraphState
from app.services.fund_service import FundService
from app.services.llm import service as llm_service_module
from app.services.llm.registry import _build_chat_model
from app.services.llm.service import LLMService


class LegacyRootState(TypedDict):
    messages: Annotated[list, add_messages]


class LegacySelectionState(TypedDict):
    messages: Annotated[list, add_messages]
    active_call: dict
    selection: FundSelectionAction
    owner_id: int


def option(code, name):
    return SimpleNamespace(fund_code=code, fund_name=name, fund_type="混合型", is_held=False, is_watchlisted=False)


@pytest.fixture
def scenario(monkeypatch):
    state = SimpleNamespace(
        keyword="示例成长",
        calls=[],
        identity=SimpleNamespace(id="fund-selection-session", user_id=42, username="tester"),
        results=[
            option("000001", "示例成长A"),
            option("000002", "示例成长C"),
            option("000003", "示例成长精选A"),
            option("000004", "示例成长精选C"),
        ],
        extra_calls=[],
    )
    state.search = AsyncMock(side_effect=lambda *args: state.results)
    monkeypatch.setattr(selection_module.fund_service, "search_analysis_candidates", state.search)
    monkeypatch.setattr(chatbot, "cache_service", InMemoryCacheService())
    monkeypatch.setattr(
        chatbot.user_profile_service,
        "execution_profiles",
        AsyncMock(
            return_value=[
                {
                    "name": "fixture",
                    "model": "fixture",
                    "api_key": "",
                    "base_url": "https://fixture.example/v1",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    monkeypatch.setattr(settings, "SESSION_NAMING_ENABLED", False)
    monkeypatch.setattr(limiter, "enabled", False)
    state.agent = LangGraphAgent()
    state.agent._graph = state.agent._build_graph(InMemorySaver())

    state.evidence_calls = []

    def evidence_tool(name):
        async def invoke(args):
            state.evidence_calls.append((name, args))
            data = {"fund_code": args.get("fund_code"), "source": "public_fixture"}
            if name == "get_portfolio_snapshot":
                data = {"status": "empty", "summary": {"fund_count": 0, "total_market_value": 0}, "positions": []}
            return "[TOOL_OK]\n" + json.dumps(data)

        return SimpleNamespace(ainvoke=invoke)

    for name in (
        "get_portfolio_snapshot",
        "get_fund_snapshot",
        "get_fund_analysis_data",
        "get_fund_holdings",
        "get_fund_managers",
        "get_fund_announcements",
        "get_fund_sectors",
        "get_market_context",
        "get_market_events",
    ):
        state.agent.tools_by_name[name] = evidence_tool(name)

    async def respond(messages, *args, **kwargs):
        state.calls.append(messages)
        if len(state.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "resolve_fund_for_analysis",
                        "args": {"keyword": state.keyword},
                        "id": "fund-resolve",
                        "type": "tool_call",
                    },
                    *state.extra_calls,
                ],
            )
        return AIMessage(content="使用已确认的基金继续分析。")

    state.agent.llm_service = SimpleNamespace(
        get_llm=lambda: SimpleNamespace(model_name="fixture", get_name=lambda: "fixture"),
        call=respond,
    )
    monkeypatch.setattr(session_lock.database_service, "get_session", AsyncMock(return_value=object()))
    monkeypatch.setattr(chatbot, "agent", state.agent)
    state.app = FastAPI()
    state.app.state.limiter = limiter
    state.app.include_router(chatbot.router, prefix="/chatbot")
    state.app.dependency_overrides[get_current_session] = lambda: state.identity
    return state


async def start(client, stream=False):
    response = await client.post(
        "/chatbot/chat/stream" if stream else "/chatbot/chat",
        json={
            "messages": [{"role": "user", "content": "分析示例成长的潜力"}],
        },
    )
    assert response.status_code == 200, response.text
    if stream:
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        return frames[-1]["pending_action"]
    return response.json()["pending_action"]


def client_for(state):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=state.app), base_url="http://test")


@pytest.mark.parametrize("stream", [False, True])
async def test_top_three_persist_pause_and_resume_original_research(scenario, stream):
    async with client_for(scenario) as client:
        pending = await start(client, stream)
        assert pending["kind"] == "fund_selection"
        assert [item["fund_code"] for item in pending["candidates"]] == ["000001", "000002", "000003"]
        assert len(scenario.calls) == 1
        scenario.search.assert_awaited_once_with("示例成长")
        recovered = (await client.get("/chatbot/pending-action")).json()["pending_action"]
        assert recovered == pending
        response = await client.post(
            "/chatbot/fund-selection/decision",
            json={
                "interrupt_id": pending["interrupt_id"],
                "decision": "select",
                "fund_code": "000002",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None and len(scenario.calls) == 2
        assert scenario.search.await_count == 1
        messages = (
            await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        ).values["messages"]
        tool = next(item for item in messages if isinstance(item, ToolMessage) and item.tool_call_id == "fund-resolve")
        data = json.loads(tool.content.splitlines()[1])
        assert data["fund"]["fund_code"] == "000002" and data["confirmed_by_user"]
        snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        outcome = FundSelectionResult.model_validate(snapshot.values["fund_selection_result"])
        assert outcome.fund.fund_code == "000002" and outcome.confirmed_by_user
        assert outcome.turn_id == snapshot.values["turn_id"]
        assert "actual_fund_codes" in str(scenario.calls[-1])
        assert snapshot.values["research_result"].fund_codes == ["000002"]
        assert sum(name == "get_fund_snapshot" for name, _ in scenario.evidence_calls) == 1
        assert not any(
            "000001" in str(message.content) for message in scenario.calls[-1] if isinstance(message, ToolMessage)
        )


async def test_structured_not_found_does_not_depend_on_tool_body_json(scenario, monkeypatch):
    scenario.results = []
    original = selection_module._complete

    def malformed_body(*args, **kwargs):
        command = original(*args, **kwargs)
        command.update["messages"][0].content = "[TOOL_OK]\n{broken-json"
        return command

    monkeypatch.setattr(selection_module, "_complete", malformed_body)
    async with client_for(scenario) as client:
        response = await client.post(
            "/chatbot/chat", json={"messages": [{"role": "user", "content": "分析不存在的基金"}]}
        )
    assert response.status_code == 200
    assert "没有找到" in response.json()["messages"][-1]["content"]
    assert len(scenario.calls) == 1


@pytest.mark.parametrize("stream", [False, True])
async def test_new_question_clears_cancelled_result_and_gets_new_turn_id(scenario, stream):
    async with client_for(scenario) as client:
        pending = await start(client)
        await client.post(
            "/chatbot/fund-selection/decision", json={"interrupt_id": pending["interrupt_id"], "decision": "cancel"}
        )
    config = {"configurable": {"thread_id": scenario.identity.id}}
    before = await scenario.agent._graph.aget_state(config)
    cancelled = FundSelectionResult.model_validate(before.values["fund_selection_result"])
    assert cancelled.status == "cancelled" and cancelled.turn_id == before.values["turn_id"]
    messages = [Message(role="user", content="现在回答另外一个问题")]
    if stream:
        async for _ in scenario.agent.get_stream_response(messages, scenario.identity.id, user_id="42"):
            pass
    else:
        await scenario.agent.get_response(messages, scenario.identity.id, user_id="42")
    after = await scenario.agent._graph.aget_state(config)
    assert after.values["turn_id"] != before.values["turn_id"]
    assert after.values["fund_selection_result"] is None
    assert len(scenario.calls) == 2


async def test_legacy_selection_checkpoint_with_dict_call_and_no_turn_id_can_resume(scenario):
    async def legacy_search(state):
        call = state["messages"][-1].tool_calls[0]
        return Command(
            update={
                "active_call": dict(call),
                "selection": FundSelectionAction(
                    keyword="示例成长",
                    candidates=[
                        {"fund_code": "000001", "fund_name": "示例成长A"},
                        {"fund_code": "000002", "fund_name": "示例成长C"},
                    ],
                ),
                "owner_id": 42,
            },
            goto="choose",
        )

    async def legacy_choose(state):
        interrupt(state["selection"].model_dump(mode="json"))
        raise AssertionError("resume should execute upgraded node")

    async def legacy_chat(state, config):
        return await scenario.agent._chat(GraphState(messages=state["messages"]), config)

    child = StateGraph(LegacySelectionState)
    child.add_node("search", legacy_search, destinations=("choose",))
    child.add_node("choose", legacy_choose)
    child.set_entry_point("search")
    root = StateGraph(LegacyRootState)
    root.add_node("chat", legacy_chat, destinations=("fund_selection", END))
    root.add_node("fund_selection", child.compile(name="fund_target_selection"))
    root.add_edge("fund_selection", "chat")
    root.set_entry_point("chat")
    saver = InMemorySaver()
    scenario.agent._graph = root.compile(checkpointer=saver)
    async with client_for(scenario) as client:
        pending = await start(client)
        old = await scenario.agent._graph.aget_state(
            {"configurable": {"thread_id": scenario.identity.id}}, subgraphs=True
        )
        assert "turn_id" not in old.values and "turn_id" not in old.tasks[0].state.values
        assert isinstance(old.tasks[0].state.values["active_call"], dict)
        scenario.agent._graph = scenario.agent._build_graph(saver)
        response = await client.post(
            "/chatbot/fund-selection/decision",
            json={"interrupt_id": pending["interrupt_id"], "decision": "select", "fund_code": "000002"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
    current = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
    result = FundSelectionResult.model_validate(current.values["fund_selection_result"])
    assert result.fund.fund_code == "000002" and result.confirmed_by_user
    assert len(scenario.calls) == 2


@pytest.mark.parametrize(
    "keyword,results,expected",
    [
        ("示例成长C", [option("000001", "示例成长C精选"), option("000002", "示例成长C")], "000002"),
        ("000002", [option("000001", "别的基金"), option("000002", "示例成长C")], "000002"),
        ("示例成长A", [option("000001", "示例成长A")], "000001"),
        ("不存在", [], None),
        ("000009", [option("000001", "模糊匹配")], None),
        ("示例成长A", [option("000001", "示例成长A"), option("000001", "示例成长A")], "000001"),
    ],
)
async def test_unique_code_exact_name_empty_and_deduplicated_results(scenario, keyword, results, expected):
    scenario.keyword, scenario.results = keyword, results
    async with client_for(scenario) as client:
        assert await start(client) is None
    messages = (await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})).values[
        "messages"
    ]
    data = json.loads(next(item for item in messages if isinstance(item, ToolMessage)).content.splitlines()[1])
    assert data["status"] == ("resolved" if expected else "not_found")
    assert (data["fund"]["fund_code"] if data["fund"] else None) == expected


async def test_invalid_old_other_session_and_chat_cannot_resume(scenario):
    async with client_for(scenario) as client:
        pending = await start(client)
        body = {"interrupt_id": pending["interrupt_id"], "decision": "select", "fund_code": "000002"}
        assert (
            await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "选第二个"}]})
        ).status_code == 409
        assert (
            await client.post("/chatbot/fund-selection/decision", json={**body, "fund_code": "000004"})
        ).status_code == 422
        assert (
            await client.post("/chatbot/fund-selection/decision", json={**body, "interrupt_id": "stale"})
        ).status_code == 409
        original = scenario.identity
        scenario.identity = SimpleNamespace(id="other-session", user_id=43, username="other")
        assert (await client.get("/chatbot/pending-action")).json()["pending_action"] is None
        assert (await client.post("/chatbot/fund-selection/decision", json=body)).status_code == 409
        scenario.identity = original
        assert (await client.post("/chatbot/fund-selection/decision", json=body)).status_code == 200
        assert (await client.post("/chatbot/fund-selection/decision", json=body)).status_code == 409


async def test_cancel_stops_without_another_llm_call(scenario):
    async with client_for(scenario) as client:
        pending = await start(client)
        response = await client.post(
            "/chatbot/fund-selection/decision",
            json={
                "interrupt_id": pending["interrupt_id"],
                "decision": "cancel",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
        assert "已取消" in response.json()["messages"][-1]["content"]
        assert len(scenario.calls) == 1 and scenario.search.await_count == 1


async def test_guessed_same_batch_tool_is_not_executed_and_messages_are_paired(scenario):
    scenario.extra_calls = [
        {"name": "get_fund_snapshot", "args": {"fund_code": "000001"}, "id": "guess", "type": "tool_call"}
    ]
    tool_call = AsyncMock(return_value='[TOOL_OK]\n{"fund_code":"000002"}')
    scenario.agent.tools_by_name["get_fund_snapshot"] = SimpleNamespace(ainvoke=tool_call)
    async with client_for(scenario) as client:
        pending = await start(client)
        response = await client.post(
            "/chatbot/fund-selection/decision",
            json={
                "interrupt_id": pending["interrupt_id"],
                "decision": "select",
                "fund_code": "000002",
            },
        )
        assert response.status_code == 200, response.text
    tool_call.assert_awaited_once_with({"fund_code": "000002"})
    messages = (await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})).values[
        "messages"
    ]
    assert {item.tool_call_id for item in messages if isinstance(item, ToolMessage)} == {"fund-resolve", "guess"}


async def test_search_failure_returns_safe_error_and_does_not_interrupt(scenario):
    scenario.search.side_effect = RuntimeError("secret-private")
    async with client_for(scenario) as client:
        assert await start(client) is None
    messages = (await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})).values[
        "messages"
    ]
    result = next(item.content for item in messages if isinstance(item, ToolMessage))
    assert "FUND_SEARCH_FAILED" in result and "secret-private" not in result


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "select"},
        {"decision": "cancel", "fund_code": "000001"},
        {"decision": "select", "fund_code": "bad"},
        {"decision": "select", "fund_code": "000001", "user_id": 43},
    ],
)
def test_strict_decision_protocol(body):
    with pytest.raises(ValueError):
        FundSelectionDecision.model_validate({"interrupt_id": "real", **body})


async def test_direct_response_does_not_treat_text_as_selection(scenario):
    async with client_for(scenario) as client:
        await start(client)
    await scenario.agent.get_response([Message(role="user", content="确认")], scenario.identity.id, user_id="42")
    assert len(scenario.calls) == 1
    assert await scenario.agent.get_pending_holding_review(scenario.identity.id) is not None


@pytest.mark.parametrize("candidate_count", [1, 4])
async def test_real_fuzzy_search_pauses_for_confirmation_even_with_one_candidate(
    scenario, monkeypatch, candidate_count
):
    reader = FundService()
    directory = [
        ("000001", "平安科技创新混合A"),
        ("000002", "平安科技创新混合C"),
        ("000003", "平安科技创新混合E"),
        ("000004", "平安科技创新3年封闭混合A"),
    ]
    catalog = AsyncMock(return_value=directory[:candidate_count])
    monkeypatch.setattr(reader, "name_directory", catalog)
    monkeypatch.setattr(selection_module.fund_service, "search_analysis_candidates", reader.search_analysis_candidates)
    scenario.keyword = "平安科技混合"
    async with client_for(scenario) as client:
        pending = await start(client)
        assert pending["kind"] == "fund_selection"
        assert [item["fund_code"] for item in pending["candidates"]] == ["000001", "000002", "000003"][
            :candidate_count
        ]
        assert len(scenario.calls) == 1
        response = await client.post(
            "/chatbot/fund-selection/decision",
            json={
                "interrupt_id": pending["interrupt_id"],
                "decision": "select",
                "fund_code": "000001",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None and catalog.await_count == 1


async def test_confirmation_survives_report_failure_and_continues_without_reselection(scenario):
    original = scenario.agent.llm_service.call
    report_calls = 0

    async def respond(messages, **kwargs):
        nonlocal report_calls
        if kwargs.get("max_tokens"):
            report_calls += 1
            if report_calls == 1:
                raise RuntimeError("fixture report timeout")
        return await original(messages, **kwargs)

    scenario.agent.llm_service.call = respond
    async with client_for(scenario) as client:
        pending = await start(client)
        choice = {"interrupt_id": pending["interrupt_id"], "decision": "select", "fund_code": "000002"}
        failed = await client.post("/chatbot/fund-selection/decision", json=choice)
        assert failed.status_code == 503
        state = await client.get("/chatbot/pending-action")
        data = state.json()
        assert data["pending_action"] is None
        assert data["continuation"]["selected_fund_code"] == "000002"
        before_calls = list(scenario.evidence_calls)
        assert (await client.post("/chatbot/continue", json={"turn_id": "old-turn"})).status_code == 409
        completed = await client.post("/chatbot/continue", json={"turn_id": data["continuation"]["turn_id"]})
        assert completed.status_code == 200, completed.text
        assert completed.json()["pending_action"] is None and completed.json()["continuation"] is None
        assert scenario.search.await_count == 1 and report_calls == 2
        assert scenario.evidence_calls == before_calls
        history = (await client.get("/chatbot/messages")).json()["messages"]
        last = history[-1]
        assert last["content"].startswith("使用已确认的基金继续分析。")
        assert "数据来源核对" not in last["content"]
        assert last["research_citations"]["coverage"][0].startswith("研究对象：")
        again = await client.post("/chatbot/continue", json={"turn_id": data["continuation"]["turn_id"]})
        assert again.status_code == 200 and report_calls == 2


class ResearchReportStream(httpx.AsyncByteStream):
    """报告持续输出的总时长超过首段等待；模拟 GLM 先推理再给正文."""

    async def __aiter__(self):
        """持续提供有效进度，不输出隐藏推理正文给客户端."""
        deltas = [{"reasoning_content": "private thinking"}] * 7 + [{"content": "已确认基金的研究报告。"}]
        for delta in deltas:
            await asyncio.sleep(0.045)
            event = {
                "id": "fixture-report",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            yield ("data: " + json.dumps(event) + "\n\n").encode()
        yield b"data: [DONE]\n\n"


class PausedReportStream(httpx.AsyncByteStream):
    """正文已经返回时暂停，便于验证客户端断线确实停止 SDK 请求."""

    def __init__(self) -> None:
        """不允许模拟报告在断线之前自行完成."""
        self.closed = False

    async def __aiter__(self):
        """真实 SSE 格式输出足够长的正文，然后一直等待取消."""
        event = {
            "id": "fixture-report",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fixture",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "正在输出已确认基金的分析内容。" * 8},
                    "finish_reason": None,
                }
            ],
        }
        yield ("data: " + json.dumps(event) + "\n\n").encode()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        """SDK 关闭底层连接时记录清理结果."""
        self.closed = True


async def test_selection_stream_outputs_before_finish_and_disconnect_preserves_resume(scenario, monkeypatch):
    wire = PausedReportStream()

    async def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=wire)

    async with client_for(scenario) as client, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as upstream:
        pending = await start(client, stream=True)
        model = _build_chat_model("fixture", "fixture", "https://fixture.invalid/v1", http_async_client=upstream)
        monkeypatch.setattr(llm_service_module, "_build_chat_model", lambda *_args, **_kwargs: model)
        scenario.agent.llm_service = LLMService()
        response = await chatbot._stream_agent_resume(
            scenario.identity,
            FundSelectionDecision(
                interrupt_id=pending["interrupt_id"],
                decision="select",
                fund_code="000002",
            ),
        )
        assert (await anext(response.body_iterator)).startswith(": connected")
        first = await asyncio.wait_for(anext(response.body_iterator), timeout=5)
        frame = json.loads(first[6:])
        assert frame["content"].startswith("正在输出") and not frame["done"]
        key = chatbot.cache_key("agent:holding-decision", scenario.identity.id)
        assert await chatbot.cache_service.acquire_lock(key, ttl=60, fail_open=False) is None
        await response.body_iterator.aclose()
        assert wire.closed
        lock = await chatbot.cache_service.acquire_lock(key, ttl=60, fail_open=False)
        assert lock is not None
        await chatbot.cache_service.release_lock(lock)
        continuation = await scenario.agent.get_run_continuation(scenario.identity.id)
        assert continuation is not None and continuation.selected_fund_code == "000002"
        assert scenario.search.await_count == 1


@pytest.mark.parametrize("resume", ["selection", "continuation"])
async def test_report_progress_survives_nonstreaming_http_resume(scenario, monkeypatch, resume):
    """覆盖真正的选择/继续 API、检查点及 SDK，不借助 graph messages 回调开启流式."""
    requests = []

    async def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if not payload.get("stream"):
            # 非流式直到完整报告才返回，旧实现会在这之前误触发首段超时。
            await asyncio.sleep(0.4)
            return httpx.Response(200, json={})
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=ResearchReportStream())

    async with client_for(scenario) as client, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as upstream:
        pending = await start(client, stream=True)
        choice = {"interrupt_id": pending["interrupt_id"], "decision": "select", "fund_code": "000002"}
        if resume == "continuation":
            scenario.agent.llm_service.call = AsyncMock(side_effect=RuntimeError("fixture interrupted report"))
            assert (await client.post("/chatbot/fund-selection/decision", json=choice)).status_code == 503
            continuation = (await client.get("/chatbot/pending-action")).json()["continuation"]
            before_evidence = list(scenario.evidence_calls)

        monkeypatch.setattr(settings, "LLM_REQUEST_TIMEOUT", 0.18)
        monkeypatch.setattr(settings, "LLM_STREAM_IDLE_TIMEOUT", 0.12)
        monkeypatch.setattr(settings, "LLM_TOTAL_TIMEOUT", 1.5)
        model = _build_chat_model("fixture", "fixture", "https://fixture.invalid/v1", http_async_client=upstream)
        monkeypatch.setattr(llm_service_module, "_build_chat_model", lambda *_args, **_kwargs: model)
        scenario.agent.llm_service = LLMService()

        response = (
            await client.post("/chatbot/fund-selection/decision", json=choice)
            if resume == "selection"
            else await client.post("/chatbot/continue", json={"turn_id": continuation["turn_id"]})
        )
        assert response.status_code == 200, response.text
        # 非流式恢复：正文不再追加尾注，证据与覆盖在结构化字段里。
        payload = response.json()["messages"][-1]
        assert payload["content"].startswith("已确认基金的研究报告。")
        assert "数据来源核对" not in payload["content"]
        assert payload["research_citations"]["coverage"][0].startswith("研究对象：")
        assert response.json()["pending_action"] is None and response.json()["continuation"] is None
        assert "private thinking" not in response.text
        assert scenario.search.await_count == 1
        assert len(requests) == 1 and requests[0]["stream"] is True
        assert "000002" in json.dumps(requests[0]["messages"])
        if resume == "continuation":
            assert scenario.evidence_calls == before_evidence
        snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        assert snapshot.values["research_result"].fund_codes == ["000002"] and not snapshot.next


def stream_frames(response: httpx.Response) -> list[dict]:
    """忽略心跳，只解析真正的 SSE 数据帧."""
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


async def test_selection_and_continuation_stream_validate_before_headers(scenario):
    async with client_for(scenario) as client:
        pending = await start(client, stream=True)
        body = {"interrupt_id": pending["interrupt_id"], "decision": "select", "fund_code": "000002"}
        assert (
            await client.post("/chatbot/fund-selection/decision/stream", json={**body, "fund_code": "000004"})
        ).status_code == 422
        assert (
            await client.post("/chatbot/fund-selection/decision/stream", json={**body, "interrupt_id": "stale"})
        ).status_code == 409
        assert (await client.post("/chatbot/continue/stream", json={"turn_id": "stale"})).status_code == 409
        lock = await chatbot.cache_service.acquire_lock(
            chatbot.cache_key("agent:holding-decision", scenario.identity.id), ttl=60, fail_open=False
        )
        assert lock is not None
        assert (await client.post("/chatbot/fund-selection/decision/stream", json=body)).status_code == 409
        await chatbot.cache_service.release_lock(lock)
        response = await client.post("/chatbot/fund-selection/decision/stream", json=body)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        frames = stream_frames(response)
        streamed = "".join(item["content"] for item in frames)
        assert streamed.startswith("使用已确认的基金继续分析。")
        assert "数据来源核对" not in streamed
        assert frames[-1]["done"] and frames[-1]["pending_action"] is None and frames[-1]["continuation"] is None
        assert scenario.search.await_count == 1 and len(scenario.calls) == 2
        assert (await client.post("/chatbot/fund-selection/decision/stream", json=body)).status_code == 409
        snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        citations = snapshot.values["messages"][-1].additional_kwargs["research_citations"]
        assert citations["coverage"][0].startswith("研究对象：")
        completed = await client.post("/chatbot/continue/stream", json={"turn_id": snapshot.values["turn_id"]})
        assert completed.status_code == 200 and len(scenario.calls) == 2


async def test_stream_failure_keeps_confirmation_and_continues_without_repeating_evidence(scenario):
    original = scenario.agent.llm_service.call

    async def fail_report(messages, **kwargs):
        if kwargs:
            raise RuntimeError("private provider error")
        return await original(messages, **kwargs)

    scenario.agent.llm_service.call = fail_report
    async with client_for(scenario) as client:
        pending = await start(client, stream=True)
        response = await client.post(
            "/chatbot/fund-selection/decision/stream",
            json={
                "interrupt_id": pending["interrupt_id"],
                "decision": "select",
                "fund_code": "000002",
            },
        )
        frames = stream_frames(response)
        assert frames[-1]["done"] and frames[-1]["pending_action"] is None
        assert "private provider error" not in response.text
        assert "继续" in frames[-1]["content"]
        continuation = frames[-1]["continuation"]
        assert continuation["selected_fund_code"] == "000002"
        evidence_before = list(scenario.evidence_calls)
        scenario.agent.llm_service.call = original
        result = await client.post("/chatbot/continue/stream", json={"turn_id": continuation["turn_id"]})
        finished = stream_frames(result)
        assert finished[-1]["continuation"] is None
        finished_text = "".join(item["content"] for item in finished)
        assert finished_text.startswith("使用已确认的基金继续分析。")
        assert "数据来源核对" not in finished_text
        snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        citations = snapshot.values["messages"][-1].additional_kwargs["research_citations"]
        assert citations["coverage"][0].startswith("研究对象：")
        assert scenario.evidence_calls == evidence_before and scenario.search.await_count == 1


async def test_continue_cannot_answer_or_skip_a_real_human_interrupt(scenario):
    async with client_for(scenario) as client:
        pending = await start(client)
        config = {"configurable": {"thread_id": scenario.identity.id}}
        state = await scenario.agent._graph.aget_state(config)
        assert (await client.get("/chatbot/pending-action")).json()["continuation"] is None
        response = await client.post("/chatbot/continue", json={"turn_id": state.values["turn_id"]})
        assert response.status_code == 409
        assert (await client.get("/chatbot/pending-action")).json()["pending_action"] == pending


@pytest.mark.parametrize("endpoint", ["/chatbot/chat", "/chatbot/chat/stream"])
async def test_text_continue_preserves_selected_target_and_original_turn(scenario, endpoint):
    original = scenario.agent.llm_service.call
    failed = False

    async def respond(messages, **kwargs):
        nonlocal failed
        if kwargs and not failed:
            failed = True
            raise RuntimeError("fixture failure")
        return await original(messages, **kwargs)

    scenario.agent.llm_service.call = respond
    async with client_for(scenario) as client:
        pending = await start(client)
        response = await client.post(
            "/chatbot/fund-selection/decision",
            json={
                "interrupt_id": pending["interrupt_id"],
                "decision": "select",
                "fund_code": "000002",
            },
        )
        assert response.status_code == 503
        before = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        resumed = await client.post(endpoint, json={"messages": [{"role": "user", "content": "继续分析"}]})
        assert resumed.status_code == 200, resumed.text
        after = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        assert after.values["turn_id"] == before.values["turn_id"]
        assert after.values["research_result"].fund_codes == ["000002"] and not after.next
        assert scenario.search.await_count == 1
        if endpoint.endswith("stream"):
            frames = [json.loads(line[6:]) for line in resumed.text.splitlines() if line.startswith("data: ")]
            resumed = "".join(frame["content"] for frame in frames)
            assert resumed.startswith("使用已确认的基金继续分析。")
            assert "数据来源核对" not in resumed
            citations = after.values["messages"][-1].additional_kwargs["research_citations"]
            assert citations["coverage"][0].startswith("研究对象：")


async def test_new_chat_cannot_overwrite_a_running_human_resume(scenario):
    original = scenario.agent.llm_service.call
    entered = asyncio.Event()
    release = asyncio.Event()

    async def respond(messages, **kwargs):
        if kwargs:
            entered.set()
            await release.wait()
        return await original(messages, **kwargs)

    scenario.agent.llm_service.call = respond
    async with client_for(scenario) as client:
        pending = await start(client)
        choice = asyncio.create_task(
            client.post(
                "/chatbot/fund-selection/decision",
                json={
                    "interrupt_id": pending["interrupt_id"],
                    "decision": "select",
                    "fund_code": "000002",
                },
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            blocked = await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "新问题"}]})
            assert blocked.status_code == 409
        finally:
            release.set()
            answer = await choice
        assert answer.status_code == 200
        state = await scenario.agent._graph.aget_state({"configurable": {"thread_id": scenario.identity.id}})
        assert state.values["research_result"].fund_codes == ["000002"] and not state.next


@pytest.mark.parametrize("endpoint", ["/chatbot/chat", "/chatbot/chat/stream"])
async def test_general_human_question_survives_refresh_and_completes_original_flow(scenario, endpoint):
    calls = []

    async def respond(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "ask_human", "args": {"question": "你的投资期限是多久？"}, "id": "question"}],
            )
        assert any(isinstance(message, ToolMessage) and message.content == "长期" for message in messages)
        return AIMessage(content="已根据长期目标继续处理。")

    scenario.agent.llm_service.call = respond
    async with client_for(scenario) as client:
        response = await client.post(
            "/chatbot/chat", json={"messages": [{"role": "user", "content": "先确认我的投资期限"}]}
        )
        assert response.status_code == 200
        pending = (await client.get("/chatbot/pending-action")).json()["pending_action"]
        assert pending["kind"] == "human_question" and pending["question"] == "你的投资期限是多久？"
        assert (await client.get("/chatbot/messages")).json()["pending_action"] == pending
        completed = await client.post(endpoint, json={"messages": [{"role": "user", "content": "长期"}]})
        assert completed.status_code == 200
        state = (await client.get("/chatbot/pending-action")).json()
        assert state["pending_action"] is None and state["continuation"] is None
        assert len(calls) == 2


async def test_prior_report_is_not_restreamed_as_the_new_answer(scenario):
    """挂载成父节点的子图会把整段历史当成自己的输出重发；上一轮报告不能变成本轮答案."""
    phase = {"text": "OLD-REPORT-上一轮历史报告正文"}
    calls = []

    async def respond(messages, *args, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "resolve_fund_for_analysis",
                        "args": {"keyword": scenario.keyword},
                        "id": "fund-resolve",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content=phase["text"])

    scenario.agent.llm_service.call = respond
    async with client_for(scenario) as client:
        pending = await start(client)
        decided = await client.post(
            "/chatbot/fund-selection/decision",
            json={"interrupt_id": pending["interrupt_id"], "decision": "select", "fund_code": "000002"},
        )
        assert decided.status_code == 200, decided.text

    history = await scenario.agent.get_chat_history(scenario.identity.id)
    assert any("OLD-REPORT" in message.content for message in history), "第一轮报告应已入库"

    # 选基金面板必然经过 fund_selection 解析代码，这正是历史被重新发射的那个节点。
    phase["text"] = "NEW-ANSWER-本轮新回答"
    answer = "".join(
        [
            chunk
            async for chunk in scenario.agent.get_stream_response(
                [Message(role="user", content="请分析这只基金：000002")],
                scenario.identity.id,
                user_id="42",
                research_fund_codes=["000002"],
            )
            if isinstance(chunk, str)
        ]
    )
    assert "NEW-ANSWER" in answer
    assert "OLD-REPORT" not in answer
