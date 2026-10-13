"""新增研究任务、真实数据卡片与完整账本试算的回归测试."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph.research import build_research_subgraph, evidence_from_text, verified_report_cards
from app.agent.graph.task_router import route_task
from app.agent.skills import read_skill
from app.agent.tools.result import ToolResult
from app.schemas.fund_selection import FundSelectionOption, FundSelectionResult
from app.schemas.research import ResearchGraphState, ResearchRequest, ResearchTask
from app.schemas.research_card import RESEARCH_CARD_ADAPTER, StockChartReference, card_code_block
from app.services.portfolio_service import PortfolioService, fund_repository, portfolio_repository
from app.services.stock_research_service import stock_research_service, market_service
from app.utils.task_routing import (
    explicitly_supplied_operation_amount,
    infer_research_request,
    request_after_fund_selection,
)
from app.analytics.allocation import position_weight
from app.utils.clock import utc_now


@pytest.mark.parametrize(
    "text,intent",
    [
        ("分析sh600519的潜力", "stock_research"),
        ("研究hk00700", "stock_research"),
        ("分析usAAPL", "stock_research"),
        ("分析BK1234", "sector_research"),
        ("分析股票600519", None),
        ("分析科技板块", None),
        ("分析000001", "fund_research"),
    ],
)
def test_domain_routing_never_confuses_stock_sector_and_fund(text, intent):
    request = infer_research_request(text)
    assert (request.intent if request else None) == intent


def test_model_cannot_invent_listing_or_sector_identifiers():
    for args in (
        {"intent": "stock_research", "stock_symbol": "sh600519"},
        {"intent": "sector_research", "sector_query": "BK1234"},
    ):
        call = AIMessage(content="", tool_calls=[{"name": "start_research", "args": args, "id": "r"}])
        command = route_task(
            SimpleNamespace(
                messages=[HumanMessage(content="分析茅台和科技"), call], fund_selection_result=None, turn_id="t"
            )
        )
        assert command.goto == "chat"
        assert "INVALID_RESEARCH_REQUEST" in command.update["messages"][0].content


def test_existing_position_value_cannot_be_converted_to_proposed_operation_amount():
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "start_research",
                "args": {
                    "intent": "allocation_analysis",
                    "fund_queries": ["000001"],
                    "action": "increase",
                    "proposed_amount": 200,
                },
                "id": "r",
            }
        ],
    )
    state = SimpleNamespace(
        messages=[HumanMessage(content="000001市值200元，我想加仓是否合理"), call],
        fund_selection_result=None,
        turn_id="t",
    )
    assert route_task(state).goto == "chat"


@pytest.mark.parametrize(
    "value,total,expected", [(None, 100, None), (0, 100, 0), (10, 0, None), (200, 100, None), (50, 100, 0.5)]
)
def test_snapshot_weights_preserve_unknown_and_zero(value, total, expected):
    assert position_weight(value, total) == expected


def test_operation_amounts_handle_grouping_and_do_not_consume_stored_costs():
    assert explicitly_supplied_operation_amount("给000001加仓1,500元", 1500)
    assert explicitly_supplied_operation_amount("成本2000元，加仓200元", 200)
    assert not explicitly_supplied_operation_amount("成本2000元，加仓200元", 2000)
    assert not explicitly_supplied_operation_amount("市值为200元能否加仓", 200)


def test_manual_fund_choice_preserves_explicit_action_amount_depth_and_account():
    request = request_after_fund_selection("详细分析账户9能否给平安科技加仓1,500元", ["000002"])
    assert request is not None
    assert request.intent == "allocation_analysis" and request.action == "increase"
    assert request.proposed_amount == 1500 and request.account_id == 9 and request.mode == "deep"
    assert request.fund_queries == ["000002"]
    request = request_after_fund_selection("市值2000元，分析平安科技能否加仓", ["000002"])
    assert request is not None and request.proposed_amount is None


@pytest.mark.parametrize(
    "text", ["查询净值", "不要分析平安科技", "导入平安科技持仓", "分析账户养老的平安科技", "分析账户0的平安科技"]
)
def test_fund_confirmation_does_not_invent_research_or_account_scope(text):
    assert request_after_fund_selection(text, ["000002"]) is None


def test_research_request_reuses_this_turn_confirmed_fund_without_search():
    fund = FundSelectionOption(fund_code="000002", fund_name="平安科技C")
    outcome = FundSelectionResult(turn_id="t", tool_call_id="select", status="resolved", keyword="平安科技", fund=fund)
    proposal = AIMessage(
        content="",
        tool_calls=[
            {"name": "start_research", "args": {"intent": "fund_research", "fund_queries": ["000002"]}, "id": "r"}
        ],
    )
    state = SimpleNamespace(
        messages=[HumanMessage(content="分析平安科技"), proposal], fund_selection_result=outcome, turn_id="t"
    )
    command = route_task(state)
    assert command.goto == "continue_research"
    assert command.update["research_task"].resolved_funds == [fund]
    state.turn_id = "new-turn"
    assert route_task(state).goto == "chat"


@pytest.mark.parametrize("skill", ["fund-allocation", "sector-analysis", "stock-analysis"])
def test_new_skills_are_whitelisted_and_have_evidence_boundaries(skill):
    assert read_skill(skill, "instructions").version == "1.0.0"
    assert read_skill(skill, "evidence").content


def test_only_this_turn_source_issued_chart_references_can_be_rendered():
    good = card_code_block(StockChartReference(symbol="sh600519"))
    bad = card_code_block(StockChartReference(symbol="sz000001"))
    state = ResearchGraphState(
        evidence=[
            evidence_from_text("get_stock_analysis_data", {}, ToolResult.ok({"chart_code_block": good}).to_text())
        ]
    )
    message = verified_report_cards(state, AIMessage(content="分析\n" + bad))
    assert good in message.content and bad not in message.content
    assert "本轮证据不一致" in message.content
    assert verified_report_cards(state, AIMessage(content=good)).content.count("research-chart") == 1
    with pytest.raises(ValueError):
        RESEARCH_CARD_ADAPTER.validate_json(
            json.dumps(
                {"schema_version": 1, "type": "stock_price", "symbol": "sh600519", "url": "https://example.com"}
            )
        )


async def test_complete_snapshot_uses_batched_repositories_and_caller_scope(monkeypatch):
    rows = [
        SimpleNamespace(
            id=i,
            account_id=9,
            fund_code=f"{i:06}",
            market_value=100,
            shares=None,
            cost_amount=80,
            average_cost_nav=None,
            profit_loss=None,
            updated_at=utc_now(),
            version=1,
        )
        for i in range(1, 62)
    ]
    service = PortfolioService()
    account = AsyncMock(return_value=SimpleNamespace(id=9))
    monkeypatch.setattr(service, "ensure_account", account)
    positions = AsyncMock(return_value=rows)
    ledger = AsyncMock(return_value={})
    funds = AsyncMock(return_value={})
    navs = AsyncMock(return_value={})
    monkeypatch.setattr(portfolio_repository, "list_positions", positions)
    monkeypatch.setattr(portfolio_repository, "ledger_rows", ledger)
    monkeypatch.setattr(fund_repository, "get_funds", funds)
    monkeypatch.setattr(fund_repository, "get_latest_navs", navs)
    snapshot = await service.research_snapshot(42, 9)
    assert len(snapshot.positions) == 61 and snapshot.summary.total_market_value == 6100
    assert snapshot.summary.total_profit_loss == 1220 and snapshot.market_values_complete
    account.assert_awaited_once_with(42, 9)
    positions.assert_awaited_once_with(42, 9)
    ledger.assert_awaited_once_with(42, 9)
    assert funds.await_count == navs.await_count == 1


async def test_stock_research_keeps_partial_sources_and_does_not_send_series(monkeypatch):
    quote = AsyncMock(side_effect=RuntimeError("upstream unavailable"))
    history = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "bars": [
                {"trade_date": "2025-10-10", "close": 10},
                {"trade_date": "2026-10-10", "close": 8},
            ]
        }
    )
    monkeypatch.setattr(market_service, "get_symbol_quote", quote)
    monkeypatch.setattr(market_service, "get_symbol_history", AsyncMock(return_value=history))
    monkeypatch.setattr(market_service, "get_symbol_company", AsyncMock(return_value=None))
    data = await stock_research_service.collect("sh600519")
    assert data["available"] and "bars" not in str(data)
    assert data["price_metrics"]["observed_max_drawdown"] == pytest.approx(-0.2)
    assert "quote查询失败" in str(data["warnings"])
    assert "stock_price" in data["chart_code_block"]
    with pytest.raises(ValueError):
        await stock_research_service.collect("600519")
    assert quote.await_count == 1


async def test_snapshot_precedes_skill_plan_and_public_stock_report_is_one_call():
    calls = []
    reports = []

    async def execute(state, config):
        call = state.messages[-1].tool_calls[0]
        calls.append(call["name"])
        data = {"summary": {"fund_count": 0, "total_market_value": 0}, "positions": [], "status": "empty"}
        if call["name"] == "get_stock_analysis_data":
            data = {"chart_code_block": card_code_block(StockChartReference(symbol="sh600519"))}
        return SimpleNamespace(update={"messages": [AIMessage(content=ToolResult.ok(data).to_text())]})

    async def report(state, config, context):
        assert state.skill_name == "stock-analysis" and state.skill_instructions
        assert [call.name for call in state.tool_plan] == ["get_stock_analysis_data"]
        reports.append(context)
        return AIMessage(content="真实证据报告")

    graph = build_research_subgraph("stock_research", execute, report)
    names = list(graph.get_graph().nodes)
    assert "load_skill" in names and "portfolio_snapshot" in names and "plan_evidence" in names
    task = ResearchTask(
        turn_id="t",
        request=ResearchRequest(intent="stock_research", stock_symbol="sh600519"),
        instruction="研究sh600519",
    )
    output = await graph.ainvoke(
        ResearchGraphState(turn_id="t", research_task=task, messages=[HumanMessage(content=task.instruction)])
    )
    assert calls == ["get_portfolio_snapshot", "get_stock_analysis_data"] and len(reports) == 1
    assert "stock_price" in output["messages"][-1].content
    assert "get_positions" not in reports[0]


async def test_ambiguous_sector_never_generates_definitive_report():
    async def execute(state, config):
        data = {
            "total_matches": 2,
            "sectors": [{"name": "科技A", "sector_code": "BK1234"}, {"name": "科技B", "sector_code": "BK1235"}],
        }
        return SimpleNamespace(update={"messages": [AIMessage(content=ToolResult.ok(data).to_text())]})

    report = AsyncMock()
    task = ResearchTask(
        turn_id="t", request=ResearchRequest(intent="sector_research", sector_query="科技"), instruction="研究科技"
    )
    graph = build_research_subgraph("sector_research", execute, report)
    output = await graph.ainvoke(ResearchGraphState(turn_id="t", research_task=task))
    assert output["research_result"].status == "needs_input"
    assert "BK1234" in output["messages"][-1].content and not report.await_count
