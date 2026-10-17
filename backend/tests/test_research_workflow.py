"""真实主图：任务取证、Top3中断恢复、用户隔离、部分数据与金额边界."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import fund_selection as selection_module
from app.agent.graph.agent import LangGraphAgent
from app.agent.graph.research import evidence_from_text, report_evidence
from app.agent.graph.task_router import continue_research, route_task
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.analytics.allocation import allocation_scenario, portfolio_scenario_inputs
from app.core.config import settings
from app.schemas.chat import Message
from app.schemas.graph import GraphState
from app.schemas.research import ResearchGraphState, ResearchRequest, ResearchResult, ResearchTask
from app.schemas.research_card import StockChartReference, card_code_block
from app.schemas.agent_resume import AgentContinueRequest
from app.services.llm import service as llm_service_module
from app.services.llm.registry import _build_chat_model
from app.services.llm.service import LLMService
from app.utils.task_routing import explicitly_supplied_amount, infer_research_request


@pytest.fixture
def workflow(monkeypatch):
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    state = SimpleNamespace(calls=[], llm_calls=[], script=[], data={}, failures=set(), candidates=None)
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    state.agent = agent

    async def search(keyword):
        return (
            state.candidates
            if state.candidates is not None
            else [SimpleNamespace(fund_code=keyword, fund_name="示例基金" + keyword, fund_type="混合型")]
        )

    monkeypatch.setattr(selection_module.fund_service, "search_analysis_candidates", AsyncMock(side_effect=search))

    async def respond(messages, **kwargs):
        state.llm_calls.append((messages, kwargs))
        return state.script.pop(0) if state.script else AIMessage(content="已根据真实证据完成研究。")

    agent.llm_service = SimpleNamespace(get_llm=lambda: None, call=respond)

    def fake_tool(name):
        async def invoke(args):
            runtime = get_tool_runtime()
            state.calls.append((name, args, runtime.user_id, runtime.thread_id))
            if name in state.failures:
                return ToolResult.fail("UNAVAILABLE", "证据暂不可用").to_text()
            if name == "get_portfolio_snapshot":
                if {"get_positions", "get_portfolio"}.intersection(state.failures):
                    return ToolResult.fail("UNAVAILABLE", "持仓状态未知").to_text()
                return ToolResult.ok(
                    state.data.get(
                        name,
                        {
                            "status": "empty",
                            "summary": state.data.get("get_portfolio", {"fund_count": 0, "total_market_value": 0}),
                            "positions": state.data.get("get_positions", {"positions": []}).get("positions"),
                            "warnings": [],
                        },
                    ),
                    source="fixture",
                ).to_text()
            return ToolResult.ok(
                state.data.get(name, {"fund_code": args.get("fund_code"), "as_of": "2026-10-09"}), source="fixture"
            ).to_text()

        return SimpleNamespace(ainvoke=invoke)

    for name in (
        "get_portfolio",
        "get_portfolio_snapshot",
        "get_stock_analysis_data",
        "get_positions",
        "get_fund_snapshot",
        "get_fund_analysis_data",
        "get_fund_comparison_data",
        "get_fund_holdings",
        "get_fund_managers",
        "get_fund_announcements",
        "get_fund_sectors",
        "get_market_context",
        "get_market_events",
        "get_sector_market",
        "identify_event_portfolio_links",
    ):
        agent.tools_by_name[name] = fake_tool(name)
    return state


def research_call(**args):
    return AIMessage(content="", tool_calls=[{"name": "start_research", "args": args, "id": "start"}])


async def run(state, text, *, stream=False, session="research"):
    messages = [Message(role="user", content=text)]
    if stream:
        return "".join([chunk async for chunk in state.agent.get_stream_response(messages, session, user_id="42")])
    return await state.agent.get_response(messages, session, user_id="42")


async def snapshot(state, session="research"):
    return await state.agent._graph.aget_state({"configurable": {"thread_id": session}})


def result(saved):
    return ResearchResult.model_validate(saved.values["research_result"])


@pytest.mark.parametrize(
    "text,intent",
    [
        ("深入分析000001的潜力", "fund_research"),
        ("诊断我的持仓", "portfolio_diagnosis"),
        ("000001的净值是多少", None),
        ("解释什么是持仓诊断", None),
        ("不要分析000001", None),
        ("导入我的持仓截图", None),
        ("分析000001是否适合加仓2000元", None),
    ],
)
def test_conservative_quick_route(text, intent):
    request = infer_research_request(text)
    assert (request.intent if request else None) == intent


@pytest.mark.parametrize("stream", [False, True])
async def test_public_research_single_report_no_private_tools_and_no_orphan_messages(workflow, stream):
    output = await run(workflow, "分析000001的潜力", stream=stream)
    saved = await snapshot(workflow)
    assert result(saved).fund_codes == ["000001"]
    assert result(saved).status == "completed"
    assert len(workflow.llm_calls) == 1 and workflow.llm_calls[0][1] == {
        "max_tokens": settings.RESEARCH_REPORT_MAX_TOKENS,
    }
    assert not {"get_portfolio", "get_positions"}.intersection(name for name, *_ in workflow.calls)
    assert all(user == 42 and thread == "research" for _, _, user, thread in workflow.calls)
    assert not {"evidence", "scenario", "owner_id", "active_call"}.intersection(saved.values)
    calls = {
        call["id"]
        for message in saved.values["messages"]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    outputs = {message.tool_call_id for message in saved.values["messages"] if isinstance(message, ToolMessage)}
    assert calls == outputs
    assert "已根据真实证据" in (output if stream else output[-1].content)
    await run(workflow, "你好")
    after = await snapshot(workflow)
    assert after.values["research_task"] is None and after.values["research_result"] is None
    assert after.values["turn_id"] != saved.values["turn_id"]


class ReportWireStream(httpx.AsyncByteStream):
    """真实 SDK 的两次流式响应，不暴露厂商隐藏推理正文."""

    def __init__(self, content: str, finish_reason: str) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.closed = False

    async def __aiter__(self):
        """依次发送正文增量及明确的结束原因."""
        deltas = [{"role": "assistant", "reasoning_content": "private reasoning"}]
        deltas.extend({"content": self.content[index : index + 8]} for index in range(0, len(self.content), 8))
        for delta in deltas:
            yield (
                "data: " + json.dumps({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) + "\n\n"
            ).encode()
        yield (
            "data: "
            + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": self.finish_reason}]})
            + "\n\n"
        ).encode()
        yield b"data: [DONE]\n\n"

    async def aclose(self) -> None:
        self.closed = True


async def test_real_sdk_truncated_report_stream_and_checkpoint_both_include_the_complete_tail(workflow, monkeypatch):
    first = "## 结论\n已根据净值与持仓证据研究。\n" + "需结合披露日期判断风险。" * 6 + "\n## 数据来源\nfi"
    tail = "xture。\n## 适用条件\n缺少个人风险偏好时仅作条件分析。"
    requests = []
    wires = [ReportWireStream(first, "length"), ReportWireStream(tail, "stop")]

    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=wires[len(requests) - 1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as upstream:

        def build(model, api_key, base_url, **kwargs):
            return _build_chat_model(model, api_key, base_url, http_async_client=upstream, **kwargs)

        monkeypatch.setattr(llm_service_module, "_build_chat_model", build)
        workflow.agent.llm_service = LLMService()
        with workflow.agent.llm_service.use_profiles(
            [
                {
                    "name": "fixture",
                    "model": "glm-5.3-flash",
                    "api_key": "fixture",  # pragma: allowlist secret
                    "base_url": "https://fixture.invalid/v1",
                }
            ]
        ):
            output = await run(workflow, "分析000001的潜力", stream=True)

    saved = await snapshot(workflow)
    assert output.startswith(first + tail)
    saved_content = saved.values["messages"][-1].content
    assert saved_content.startswith(first + tail)
    assert "数据来源核对" in saved_content  # 续写完整后仍由代码补尾注
    assert result(saved).status == "completed" and not saved.next
    assert saved.values["messages"][-1].response_metadata["report_continuations"] == 1
    assert len(requests) == 2 and all(item["stream"] for item in requests)
    assert all(item["max_tokens"] == settings.RESEARCH_REPORT_MAX_TOKENS for item in requests)
    assert all(item["reasoning_effort"] == settings.LLM_REASONING_EFFORT for item in requests)
    assert all("tools" not in item for item in requests)
    assert requests[1]["messages"][-2]["content"] == first
    assert "private reasoning" not in output and all(wire.closed for wire in wires)
    assert len(workflow.calls) == len({(name, str(args)) for name, args, *_ in workflow.calls})


async def test_exhausted_report_is_continuable_without_repeating_evidence(workflow, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_REPORT_MAX_CONTINUATIONS", 1)
    workflow.script = [AIMessage(content="尚未完成。", response_metadata={"finish_reason": "length"})] * 2
    with pytest.raises(Exception, match="尚未完整生成"):
        await run(workflow, "分析000001的潜力", stream=True)
    saved = await snapshot(workflow)
    assert saved.next and saved.values["research_result"] is None
    evidence_before = list(workflow.calls)
    continuation = await workflow.agent.get_run_continuation("research")
    assert continuation is not None
    output = "".join(
        [
            chunk
            async for chunk in workflow.agent.get_stream_response(
                [], "research", user_id="42", resume=AgentContinueRequest(turn_id=continuation.turn_id)
            )
        ]
    )
    assert "已根据真实证据" in output and workflow.calls == evidence_before
    assert result(await snapshot(workflow)).status == "completed"


async def test_ambiguous_name_pauses_research_until_selection_then_resumes_original_task(workflow):
    workflow.candidates = [
        SimpleNamespace(fund_code=f"00000{i}", fund_name=f"成长基金{i}", fund_type="混合型") for i in range(1, 5)
    ]
    workflow.script = [research_call(intent="fund_research", fund_queries=["成长"])]
    await run(workflow, "分析成长基金")
    pending = await workflow.agent.get_pending_holding_review("research")
    assert pending.kind == "fund_selection" and len(pending.candidates) == 3
    assert not workflow.calls and len(workflow.llm_calls) == 1
    turn = (await snapshot(workflow)).values["turn_id"]
    await workflow.agent.resume_holding_import(
        "research",
        pending.interrupt_id,
        {"interrupt_id": pending.interrupt_id, "decision": "select", "fund_code": "000002"},
        user_id="42",
    )
    saved = await snapshot(workflow)
    assert result(saved).fund_codes == ["000002"] and saved.values["turn_id"] == turn
    assert len(workflow.llm_calls) == 2
    assert all(
        args.get("fund_code") == "000002" for name, args, *_ in workflow.calls if name != "get_portfolio_snapshot"
    )


async def test_cancellation_never_collects_evidence(workflow):
    workflow.candidates = [SimpleNamespace(fund_code="000001", fund_name="成长A", fund_type="混合型")]
    workflow.script = [research_call(intent="fund_research", fund_queries=["成长"])]
    await run(workflow, "分析成长基金")
    pending = await workflow.agent.get_pending_holding_review("research")
    await workflow.agent.resume_holding_import(
        "research", pending.interrupt_id, {"interrupt_id": pending.interrupt_id, "decision": "cancel"}, user_id="42"
    )
    assert not workflow.calls and len(workflow.llm_calls) == 1
    assert (await snapshot(workflow)).values["research_result"] is None


async def test_multiple_funds_resolved_sequentially_under_recursion_limit(workflow):
    await run(workflow, "分析000001和000002以及000003的潜力")
    assert result(await snapshot(workflow)).fund_codes == ["000001", "000002", "000003"]
    assert len(workflow.llm_calls) == 1


async def test_search_failure_stops_workflow_without_infinite_resolution_retry(workflow, monkeypatch):
    search = AsyncMock(side_effect=RuntimeError("private failure"))
    monkeypatch.setattr(selection_module.fund_service, "search_analysis_candidates", search)
    output = await run(workflow, "分析000001的潜力")
    assert result(await snapshot(workflow)).status == "needs_input"
    assert search.await_count == 1 and not workflow.calls and not workflow.llm_calls
    assert "无法核验" in output[-1].content and "private failure" not in str(output)


async def test_portfolio_diagnosis_deduplicates_top_three_and_reports_scope(workflow):
    rows = [{"fund_code": code, "market_value": 100} for code in ["000001", "000001", "000002", "000003", "000004"]]
    workflow.data.update(get_portfolio={"fund_count": 5, "total_market_value": 500}, get_positions={"positions": rows})
    await run(workflow, "诊断我的持仓")
    outcome = result(await snapshot(workflow))
    assert outcome.fund_codes == ["000001", "000002", "000003"] and outcome.status == "partial"
    assert any("前三只" in gap for gap in outcome.gaps)
    assert len(workflow.llm_calls) == 1


async def test_explicit_portfolio_focus_takes_priority_over_largest_funds(workflow):
    rows = [{"fund_code": code, "market_value": 100} for code in ["000001", "000002", "000003", "000004"]]
    workflow.data.update(get_portfolio={"fund_count": 4, "total_market_value": 400}, get_positions={"positions": rows})
    workflow.script = [research_call(intent="portfolio_diagnosis", fund_queries=["000004"])]
    await run(workflow, "诊断我的持仓，重点看看000004")
    assert result(await snapshot(workflow)).fund_codes == ["000004", "000001", "000002"]


@pytest.mark.parametrize("failed", [False, True])
async def test_empty_or_unavailable_portfolio_has_no_fabricated_report(workflow, failed):
    workflow.data["get_positions"] = {"positions": []}
    if failed:
        workflow.failures.add("get_positions")
    output = await run(workflow, "诊断我的持仓")
    assert result(await snapshot(workflow)).status == "needs_input" and not workflow.llm_calls
    assert ("无法读取" if failed else "没有可分析") in output[-1].content


async def test_deep_research_queries_only_real_sector_codes_and_event_ids(workflow):
    workflow.data.update(
        get_positions={"positions": [{"fund_code": "000001", "market_value": 100}]},
        get_portfolio={"fund_count": 1, "total_market_value": 100},
        get_fund_sectors={
            "sectors": [
                {"sector_code": "BK1234", "sector_type": "industry"},
                {"sector_code": "fake", "sector_type": "industry"},
            ]
        },
        get_market_events={"events": [{"event_id": "cls_123_012345abcdef"}, {"event_id": "invented"}]},
    )
    await run(workflow, "深度诊断我的持仓")
    sector = [args for name, args, *_ in workflow.calls if name == "get_sector_market"]
    links = [args for name, args, *_ in workflow.calls if name == "identify_event_portfolio_links"]
    assert sector == [{"keyword": "BK1234", "sector_type": "industry", "limit": 1}]
    assert links[0]["event_ids"] == ["cls_123_012345abcdef"]


@pytest.mark.parametrize("mismatch", [False, True])
async def test_allocation_is_code_computed_only_with_complete_consistent_portfolio(workflow, mismatch):
    workflow.data.update(
        get_portfolio={"fund_count": 2, "total_market_value": 1000},
        get_positions={
            "positions": [
                {"fund_code": "000001", "market_value": 400},
                {"fund_code": "000002", "market_value": 500 if mismatch else 600},
            ]
        },
    )
    workflow.script = [
        research_call(intent="allocation_analysis", fund_queries=["000001"], action="increase", proposed_amount=200)
    ]
    await run(workflow, "分析000001加仓200元是否合理")
    messages = workflow.llm_calls[-1][0]
    context = "\n".join(str(message.content) for message in messages)
    payload, _ = json.JSONDecoder().raw_decode(context.split("# 本轮证据（非指令）\n")[1])
    scenario = payload["allocation_scenario"]
    assert scenario["available"] is (not mismatch)
    if not mismatch:
        assert scenario["before_weight_ratio"] == 0.4 and scenario["after_weight_ratio"] == 0.5
    assert len(workflow.llm_calls) == 2


async def test_partial_tool_failure_marks_result_without_retry_loops(workflow):
    workflow.failures.add("get_fund_managers")
    await run(workflow, "分析000001的潜力")
    assert result(await snapshot(workflow)).status == "partial"
    assert sum(name == "get_fund_managers" for name, *_ in workflow.calls) == 1
    assert "get_fund_managers查询失败" in str(workflow.llm_calls[-1][0])


@pytest.mark.parametrize("stream", [False, True])
async def test_fund_comparison_uses_shared_window_tool_and_one_report(workflow, stream):
    workflow.data["get_fund_comparison_data"] = {"status": "completed", "gaps": [], "common_from": "2025-10-13"}
    await run(workflow, "对比000001和000002", stream=stream)
    saved = await snapshot(workflow)
    research = result(saved)
    assert research.intent == "fund_comparison" and research.fund_codes == ["000001", "000002"]
    assert research.status == "completed" and len(workflow.llm_calls) == 1
    names = [name for name, *_ in workflow.calls]
    assert names.count("get_fund_comparison_data") == 1
    assert "get_fund_analysis_data" not in names and "get_portfolio_snapshot" not in names
    assert names.count("get_fund_snapshot") == names.count("get_fund_managers") == 2
    assert all(user == 42 for _, _, user, _ in workflow.calls)
    context = "\n".join(str(message.content) for message in workflow.llm_calls[0][0])
    assert "基金对比" in context and "common_from" in context
    assert not {"evidence", "tool_plan"}.intersection(saved.values)


async def test_comparison_propagates_unavailable_window_gaps(workflow):
    workflow.data["get_fund_comparison_data"] = {"status": "unavailable", "gaps": ["没有共同日期"]}
    await run(workflow, "比较000001和000002")
    research = result(await snapshot(workflow))
    assert research.status == "partial" and "没有共同日期" in research.gaps


async def test_comparison_confirmations_finish_before_any_evidence(workflow):
    workflow.candidates = [
        SimpleNamespace(fund_code=f"00000{i}", fund_name=f"成长{i}", fund_type="混合型") for i in (1, 2)
    ]
    workflow.script = [research_call(intent="fund_comparison", fund_queries=["成长", "价值"])]
    await run(workflow, "比较成长和价值")
    first = await workflow.agent.get_pending_holding_review("research")
    assert first.kind == "fund_selection" and not workflow.calls
    await workflow.agent.resume_holding_import(
        "research",
        first.interrupt_id,
        {"interrupt_id": first.interrupt_id, "decision": "select", "fund_code": "000001"},
        user_id="42",
    )
    second = await workflow.agent.get_pending_holding_review("research")
    assert second.kind == "fund_selection" and not workflow.calls
    await workflow.agent.resume_holding_import(
        "research",
        second.interrupt_id,
        {"interrupt_id": second.interrupt_id, "decision": "select", "fund_code": "000002"},
        user_id="42",
    )
    assert result(await snapshot(workflow)).fund_codes == ["000001", "000002"]
    assert sum(name == "get_fund_comparison_data" for name, *_ in workflow.calls) == 1


async def test_comparison_aliases_resolving_to_same_code_require_another_object(workflow):
    workflow.candidates = [SimpleNamespace(fund_code="000001", fund_name="成长A", fund_type="混合型")]
    workflow.script = [research_call(intent="fund_comparison", fund_queries=["成长A", "成长"])]
    await run(workflow, "对比成长A和成长")
    pending = await workflow.agent.get_pending_holding_review("research")
    await workflow.agent.resume_holding_import(
        "research",
        pending.interrupt_id,
        {"interrupt_id": pending.interrupt_id, "decision": "select", "fund_code": "000001"},
        user_id="42",
    )
    assert result(await snapshot(workflow)).status == "needs_input"
    assert not workflow.calls and len(workflow.llm_calls) == 1


async def test_personal_comparison_reads_snapshot_only_when_requested(workflow):
    workflow.script = [research_call(intent="fund_comparison", fund_queries=["000001", "000002"])]
    await run(workflow, "结合我的持仓对比000001和000002")
    assert sum(name == "get_portfolio_snapshot" for name, *_ in workflow.calls) == 1


async def test_comparison_cancellation_does_not_collect_or_write_report(workflow):
    workflow.candidates = [SimpleNamespace(fund_code="000001", fund_name="成长A", fund_type="混合型")]
    workflow.script = [research_call(intent="fund_comparison", fund_queries=["成长", "价值"])]
    await run(workflow, "比较成长和价值")
    pending = await workflow.agent.get_pending_holding_review("research")
    await workflow.agent.resume_holding_import(
        "research", pending.interrupt_id, {"interrupt_id": pending.interrupt_id, "decision": "cancel"}, user_id="42"
    )
    assert not workflow.calls and len(workflow.llm_calls) == 1


async def test_deep_comparison_reuses_announcements_without_duplicate_nav_analysis(workflow):
    await run(workflow, "深入比较000001和000002")
    names = [name for name, *_ in workflow.calls]
    assert names.count("get_fund_announcements") == 2
    assert names.count("get_fund_comparison_data") == 1 and "get_fund_analysis_data" not in names


def test_router_rejects_invented_amount_and_pairs_all_calls():
    call = research_call(intent="allocation_analysis", fund_queries=["000001"], action="increase", proposed_amount=200)
    call.tool_calls.append({"name": "get_fund_snapshot", "args": {"fund_code": "000001"}, "id": "guess"})
    command = route_task(GraphState(messages=[HumanMessage(content="分析加仓000001是否合适"), call], turn_id="t"))
    assert command.goto == "chat" and {message.tool_call_id for message in command.update["messages"]} == {
        "start",
        "guess",
    }
    assert all("INVALID_RESEARCH_REQUEST" in message.content for message in command.update["messages"])
    assert explicitly_supplied_amount("加仓1.5万元", 15000)
    assert explicitly_supplied_amount("加仓1,500元", 1500)
    assert not explicitly_supplied_amount("加仓20%", 20)
    assert not explicitly_supplied_amount("加仓,,,元", 200)


@pytest.mark.parametrize("query", ["000001", "平安科技创新混合A"])
def test_model_cannot_guess_code_or_complete_name_and_bypass_top_three(query):
    command = route_task(
        GraphState(
            messages=[
                HumanMessage(content="分析平安科技混合"),
                research_call(intent="fund_research", fund_queries=[query]),
            ],
            turn_id="t",
        )
    )
    assert command.goto == "chat"
    assert "INVALID_RESEARCH_REQUEST" in command.update["messages"][0].content


def test_stale_task_never_runs_and_schema_rejects_identity():
    task = ResearchTask(
        turn_id="old", request=ResearchRequest(intent="fund_research", fund_queries=["000001"]), instruction="旧任务"
    )
    assert continue_research(GraphState(turn_id="new", research_task=task)).goto == "chat"
    with pytest.raises(ValueError):
        ResearchRequest.model_validate({"intent": "portfolio_diagnosis", "user_id": 43})


@pytest.mark.parametrize(
    "text,expected",
    [("诊断账户12的持仓", "continue_research"), ("诊断我的账户", "chat"), ("诊断账户123的持仓", "chat")],
)
def test_account_scope_requires_explicit_number(text, expected):
    call = research_call(intent="portfolio_diagnosis", account_id=12)
    assert route_task(GraphState(messages=[HumanMessage(content=text), call], turn_id="t")).goto == expected


def test_attachments_do_not_trigger_fast_portfolio_diagnosis():
    command = route_task(
        GraphState(messages=[HumanMessage(content="诊断我的持仓")], holding_import_ids=["real-image-batch"])
    )
    assert command.goto == "chat"


@pytest.mark.parametrize(
    "positions", [{}, {"positions": None}, {"positions": ["bad"]}, {"positions": [{"fund_code": "000001"}]}]
)
def test_invalid_or_incomplete_position_rows_do_not_produce_zero_target(positions):
    assert portfolio_scenario_inputs({"fund_count": 1, "total_market_value": 100}, positions, "000002") == (None, None)


def test_evidence_clipping_and_malformed_success_are_not_silently_complete():
    assert not evidence_from_text("get_positions", {}, "[TOOL_OK]\n{broken").success
    item = evidence_from_text("get_fund_managers", {}, ToolResult.ok({"body": "证据" * 10000}).to_text())
    _, gaps = report_evidence(ResearchGraphState(evidence=[item] * 20))
    assert any("部分正文" in gap for gap in gaps) and any("未纳入报告" in gap for gap in gaps)


@pytest.mark.parametrize(
    "total,target,amount,action,available",
    [
        (1000, 400, 200, "increase", True),
        (1000, 400, 200, "reduce", True),
        (1000, 400, 500, "reduce", False),
        (1000, 400, 200, "exit", False),
        (1000, 400, None, "increase", False),
        (float("nan"), 400, 200, "increase", False),
        (0, 0, 200, "build", True),
        (400, 400, 400, "exit", True),
    ],
)
def test_allocation_financial_boundaries(total, target, amount, action, available):
    scenario = allocation_scenario(total=total, target=target, amount=amount, action=action)
    assert scenario["available"] is available
    if available and action == "exit":
        assert scenario["after_fund_assets"] == 0 and scenario["after_weight_ratio"] is None


async def test_real_model_stream_withholds_unverified_chart_and_matches_saved_response(workflow):
    approved = card_code_block(StockChartReference(symbol="sh600519"))
    invented = card_code_block(StockChartReference(symbol="sz000001"))
    workflow.data["get_stock_analysis_data"] = {"chart_code_block": approved}
    model = FakeListChatModel(responses=["真实股票分析。\n" + invented + "\n后续观察。"])

    async def respond(messages, **kwargs):
        return await model.ainvoke(messages)

    workflow.agent.llm_service.call = respond
    output = await run(workflow, "分析sh600519的潜力", stream=True)
    saved = await snapshot(workflow)
    assert invented not in output and output.count(approved) == 1
    assert output == saved.values["messages"][-1].content
    assert "后续观察" in output
