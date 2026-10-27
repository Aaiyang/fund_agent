"""技能资源白名单、真实净值指标与图表协议、成本隔离及Agent图集成."""

import importlib
import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph.agent import LangGraphAgent
from app.agent.skills import read_skill
from app.agent.tools.fund import get_fund_analysis_data, get_fund_holdings, get_fund_snapshot
from app.agent.tools.load_skill import load_skill
from app.agent.tools.portfolio import get_positions
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, FUND_TOOLS, SYSTEM_TOOLS, TOOLS_VERSION
from app.agent.tools.runtime import ToolRuntimeContext, set_tool_runtime
from app.analytics.fund_analysis import nav_metrics, weekly_chart_points
from app.analytics.returns import NavPoint
from app.core.config import settings
from app.core.cache import InMemoryCacheService
from app.models.fund import Fund, FundNav
from app.schemas import Message
from app.schemas.agent_skill import LoadSkillRequest
from app.schemas.fund import FundDetailResponse, FundNavHistoryResponse, FundNavPoint, FundPerformance
from app.schemas.fund_analysis import FundAnalysisRequest, FundChartPoint, FundChartReference, FundNavChart
from app.schemas.portfolio import PositionItem
from app.services.fund_analysis_service import FundAnalysisService, normalize_points
from app.services.fund_service import FundService
from app.utils.clock import range_start

service_module = importlib.import_module("app.services.fund_analysis_service")
chart_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_analysis_data")
positions_tool_module = importlib.import_module("app.agent.tools.portfolio.get_positions")
holdings_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_holdings")
snapshot_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_snapshot")
market_tool_module = importlib.import_module("app.agent.tools.market.get_market_context")
fund_service_module = importlib.import_module("app.services.fund_service")
TODAY = date(2026, 10, 9)
START = range_start("1y", TODAY)


def nav(day, value):
    return FundNavPoint(nav_date=day, unit_nav=value)


def dense_history():
    return [nav(day, 1 + index / 1000) for index in range(366) if (day := START + timedelta(days=index)).weekday() < 5]


def chart_payload(**changes):
    return dict(
        fund_code="000001",
        title="test",
        requested_from=START,
        requested_to=TODAY,
        observed_from=START,
        observed_to=TODAY,
        as_of=TODAY,
        points=[{"date": START, "unit_nav": 1}, {"date": TODAY, "unit_nav": 1.1}],
        **changes,
    )


@pytest.mark.parametrize(
    "input",
    [
        {"skill_name": "../secret"},
        {"skill_name": "fund-analysis", "section": "../../config.py"},
        {"skill_name": "fund-analysis", "url": "https://internal"},
        {"skill_name": "fund-analysis", "user_id": 43},
    ],
)
async def test_loader_rejects_unknown_skills_paths_urls_and_identity(input):
    with pytest.raises(ValidationError):
        await load_skill.ainvoke(input)


async def test_loader_resources_are_packaged_and_read_only(monkeypatch):
    # 请求中不再访问文件；只能读模块已加载的白名单内容。
    monkeypatch.setattr("pathlib.Path.read_text", lambda *args, **kwargs: pytest.fail("request-time file IO"))
    workflow = json.loads((await load_skill.ainvoke({"skill_name": "fund-analysis"})).splitlines()[1])
    reference = json.loads(
        (await load_skill.ainvoke({"skill_name": "fund-analysis", "section": "evidence"})).splitlines()[1]
    )
    assert workflow["version"] == reference["version"] == "1.4.0"
    assert workflow["section"] == "instructions" and reference["section"] == "evidence"
    assert workflow["content"] != reference["content"] and set(workflow["available_sections"]) == {
        "instructions",
        "evidence",
    }
    assert "fund-analysis" == read_skill("fund-analysis", "instructions").name


@pytest.mark.parametrize(
    "extra",
    [{"points": []}, {"user_id": 42}, {"cost_nav": 1.2}, {"url": "https://internal"}, {"fund_code": "０００００１"}],
)
def test_analysis_inputs_cannot_supply_chart_or_private_data(extra):
    with pytest.raises(ValidationError):
        FundAnalysisRequest.model_validate({"fund_code": "000001", **extra})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0, -1])
def test_chart_rejects_nonfinite_and_nonpositive_values(bad):
    with pytest.raises(ValidationError):
        FundChartPoint(date=TODAY, unit_nav=bad)


def test_chart_rejects_unsorted_duplicate_future_endpoints_and_executable_fields():
    valid = FundNavChart.model_validate(chart_payload())
    for points in [
        list(reversed(valid.points)),
        [valid.points[0], valid.points[0]],
        [valid.points[0], FundChartPoint(date=TODAY + timedelta(days=1), unit_nav=1)],
    ]:
        with pytest.raises(ValidationError):
            FundNavChart.model_validate({**chart_payload(), "points": points})
    for changes in [
        {"as_of": START},
        {"url": "https://internal"},
        {"type": "html"},
        {"script": "alert(1)"},
        {"points": valid.points * 31},
    ]:
        with pytest.raises(ValidationError):
            FundNavChart.model_validate({**chart_payload(), **changes})


def test_daily_peak_not_lost_in_metrics_after_weekly_sampling():
    points = [NavPoint(date(2026, 10, 7), 1), NavPoint(date(2026, 10, 8), 3), NavPoint(TODAY, 1)]
    sampled = weekly_chart_points(points)
    assert [point.unit_nav for point in sampled] == [1, 1]
    metrics = nav_metrics(points, daily_quality=True)
    assert metrics.observed_max_drawdown_ratio == pytest.approx(-2 / 3)
    assert metrics.observed_change_ratio == 0 and metrics.range_position_ratio == 0
    assert metrics.annualized_nav_volatility_ratio is None


def test_constant_nav_and_missing_short_series_are_not_valuation_signals():
    assert nav_metrics([], daily_quality=False).latest_nav is None
    one = nav_metrics([NavPoint(TODAY, 1)], daily_quality=True)
    assert one.observed_change_ratio is None and one.observed_max_drawdown_ratio is None
    flat = nav_metrics([NavPoint(TODAY - timedelta(days=1), 1), NavPoint(TODAY, 1)], daily_quality=True)
    assert flat.range_position_ratio is None and flat.observed_max_drawdown_ratio == 0


def test_normalization_excludes_conflicts_bad_values_and_window_expansion():
    rows = [
        nav(TODAY, 1),
        nav(TODAY, 1),
        nav(TODAY, 2),
        nav(START, float("nan")),
        nav(START + timedelta(days=1), 0),
        nav(TODAY + timedelta(days=1), 1),
        nav(START + timedelta(days=2), 1.1),
    ]
    points, invalid, duplicate, conflict = normalize_points(rows, START, TODAY)
    assert points == [NavPoint(START + timedelta(days=2), 1.1)]
    assert (invalid, duplicate, conflict) == (3, 1, 1)


@pytest.fixture
def service(monkeypatch):
    history = AsyncMock(return_value=FundNavHistoryResponse(fund_code="000001", points=dense_history()))
    monkeypatch.setattr(service_module.fund_service, "get_nav_history", history)
    monkeypatch.setattr(service_module, "business_today", lambda: TODAY)
    reader = FundAnalysisService()
    monkeypatch.setattr(chart_tool_module, "fund_analysis_service", reader)
    set_tool_runtime(None)
    yield SimpleNamespace(reader=reader, history=history)
    set_tool_runtime(None)


async def test_one_year_window_bound_endpoints_risk_quality_and_json_roundtrip(service):
    result = await service.reader.get_data(FundAnalysisRequest(fund_code="000001"))
    service.history.assert_awaited_with("000001", start_date=START, end_date=TODAY)
    assert not result.partial and result.window_start_covered and not result.stale
    assert result.metrics.annualized_nav_volatility_ratio is not None
    assert 2 <= len(result.chart.points) <= 60 < result.valid_daily_count
    assert result.chart.points[0].date == result.observed_from and result.chart.points[-1].date == TODAY
    text = await get_fund_analysis_data.ainvoke({"fund_code": "000001"})
    data = json.loads(text.splitlines()[1])
    assert "chart" not in data and data["metrics"]["metric_basis"] == "unadjusted_unit_nav"
    block = data["chart_code_block"]
    assert block.startswith("```fund-chart\n") and block.endswith("\n```")
    restored = FundChartReference.model_validate_json(block.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert restored.fund_code == "000001" and "as_of=2026-10-09" in text
    assert set(restored.model_dump()) == {"schema_version", "type", "fund_code"}
    assert '"points":' not in text and '"unit_nav":' not in text
    assert "average_cost_nav" not in block and "cost_amount" not in block


@pytest.mark.parametrize("rows", [[], [nav(TODAY, 1)], [nav(TODAY, float("nan"))]])
async def test_insufficient_or_empty_data_cannot_make_a_chart(service, rows):
    service.history.return_value.points = rows
    result = await service.reader.get_data(FundAnalysisRequest(fund_code="000001"))
    assert result.partial and result.chart is None
    text = await get_fund_analysis_data.ainvoke({"fund_code": "000001"})
    block = json.loads(text.splitlines()[1])["chart_code_block"]
    assert json.loads(block.splitlines()[1]) == {
        "schema_version": 2,
        "type": "fund_performance",
        "fund_code": "000001",
    }
    assert "points" not in block


async def test_short_stale_gapped_or_truncated_history_keeps_actual_scope(service):
    service.history.return_value.points = [nav(TODAY - timedelta(days=90), 1), nav(TODAY - timedelta(days=30), 1.1)]
    service.history.return_value.has_more = True
    result = await service.reader.get_data(FundAnalysisRequest(fund_code="000001"))
    assert result.partial and result.stale and result.source_truncated and not result.window_start_covered
    assert result.observed_to == TODAY - timedelta(days=30) and result.max_gap_days == 60
    assert result.metrics.annualized_nav_volatility_ratio is None and result.chart.as_of == result.observed_to
    assert "stale=true" in await get_fund_analysis_data.ainvoke({"fund_code": "000001"})


async def test_malformed_daily_point_suppresses_annualized_risk(service):
    service.history.return_value.points.append(nav(TODAY - timedelta(days=10), float("nan")))
    result = await service.reader.get_data(FundAnalysisRequest(fund_code="000001"))
    assert result.invalid_count == 1 and result.partial and result.metrics.annualized_nav_volatility_ratio is None


async def test_leap_year_window_and_mismatched_fund_are_rejected(service, monkeypatch):
    monkeypatch.setattr(service_module, "business_today", lambda: date(2024, 2, 29))
    service.history.return_value.points = [nav(date(2023, 2, 28), 1), nav(date(2024, 2, 29), 1.1)]
    result = await service.reader.get_data(FundAnalysisRequest(fund_code="000001"))
    assert result.requested_from == date(2023, 2, 28)
    service.history.return_value.fund_code = "000002"
    assert (await get_fund_analysis_data.ainvoke({"fund_code": "000001"})).startswith("[TOOL_ERROR] UPSTREAM_ERROR")


async def test_unavailable_data_safe_errors_do_not_leak_credentials(service):
    service.history.side_effect = RuntimeError("db secret=private")
    text = await get_fund_analysis_data.ainvoke({"fund_code": "000001"})
    assert text.startswith("[TOOL_ERROR] UPSTREAM_ERROR") and "private" not in text


async def test_private_cost_is_runtime_scoped_and_quote_fields_are_preserved(monkeypatch):
    set_tool_runtime(ToolRuntimeContext(user_id=42, thread_id="cost", request_id=""))
    rows = AsyncMock(
        return_value=[
            PositionItem(account_id=10, fund_code="000001", average_cost_nav=1.23, average_cost_nav_derived=True)
        ]
    )
    monkeypatch.setattr(positions_tool_module, "portfolio_service", SimpleNamespace(list_positions=rows))
    data = json.loads((await get_positions.ainvoke({})).splitlines()[1])
    rows.assert_awaited_once_with(42, None)
    assert data["positions"][0]["average_cost_nav"] == 1.23 and data["positions"][0]["average_cost_nav_derived"]
    holdings = SimpleNamespace(
        quarter="2026年2季度",
        previous_quarter=None,
        industries=[],
        industries_as_of=date(2026, 6, 30),
        items=[
            SimpleNamespace(
                stock_code="600001",
                stock_name="示例",
                weight=10,
                weight_change=None,
                is_new=False,
                price=12.3,
                change_pct=1.2,
                quote_time="2026-10-09 15:00:00",
            )
        ],
    )
    monkeypatch.setattr(
        holdings_tool_module, "fund_service", SimpleNamespace(get_holdings=AsyncMock(return_value=holdings))
    )
    data = json.loads((await get_fund_holdings.ainvoke({"fund_code": "000001"})).splitlines()[1])
    assert (
        data["top_holdings"][0]["change_pct"] == 1.2 and data["top_holdings"][0]["quote_time"] == "2026-10-09 15:00:00"
    )
    card = json.loads(data["holdings_code_block"].splitlines()[1])
    assert card["report_date"] == "2026年2季度"
    assert card["items"] == [{"stock_code": "600001", "stock_name": "示例", "weight": 10}]
    assert "price" not in card["items"][0] and "average_cost_nav" not in card
    detail = FundDetailResponse(fund_code="000001", fund_name="test", performance=FundPerformance(return_1y=0.1))
    monkeypatch.setattr(
        snapshot_tool_module, "fund_service", SimpleNamespace(get_detail=AsyncMock(return_value=detail))
    )
    snapshot = await get_fund_snapshot.ainvoke({"fund_code": "000001"})
    assert json.loads(snapshot.splitlines()[1])["performance_basis"] == "unadjusted_unit_nav"
    set_tool_runtime(None)


def test_registry_and_schemas_scope():
    assert TOOLS_VERSION == "v21"
    assert get_fund_analysis_data in FUND_TOOLS and load_skill in SYSTEM_TOOLS
    assert load_skill in DEFAULT_AGENT_TOOLS and set(get_fund_analysis_data.args) == {"fund_code"}
    assert set(load_skill.args) == {"skill_name", "section"}
    assert "user_id" not in get_positions.args
    with pytest.raises(ValidationError):
        LoadSkillRequest(skill_name="fund-analysis", section="script")


@pytest.mark.parametrize("stream", [False, True])
async def test_agent_loads_skill_resources_positions_and_real_chart_over_three_turns(service, monkeypatch, stream):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    rows = AsyncMock(return_value=[PositionItem(account_id=10, fund_code="000001", average_cost_nav=1.2)])
    monkeypatch.setattr(positions_tool_module, "portfolio_service", SimpleNamespace(list_positions=rows))

    class ScriptedLLM:
        count = 0

        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            latest = next(message for message in reversed(inputs) if message.type != "system")
            if latest.type != "tool":
                name, arguments = "load_skill", {"skill_name": "fund-analysis"}
            else:
                assert latest.content.startswith("[TOOL_OK]")
                data = json.loads(latest.content.splitlines()[1])
                if latest.name == "load_skill":
                    if data["section"] == "instructions":
                        name, arguments = "load_skill", {"skill_name": "fund-analysis", "section": "evidence"}
                    else:
                        name, arguments = "get_positions", {}
                elif latest.name == "get_positions":
                    assert data["positions"][0]["average_cost_nav"] == 1.2
                    name, arguments = "get_market_context", {}
                elif latest.name == "get_market_context":
                    name, arguments = "get_fund_analysis_data", {"fund_code": "000001"}
                else:
                    assert data["metrics"]["metric_basis"] == "unadjusted_unit_nav"
                    return AIMessage(
                        content="已提供真实净值图；经理、重仓和政策未查询，不补造结论。\n" + data["chart_code_block"]
                    )
            self.count += 1
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": arguments, "id": f"skill-{self.count}", "type": "tool_call"}],
            )

    quotes = AsyncMock(
        return_value=[
            SimpleNamespace(index_code="000001", name="示例指数", close=3000, change_pct=1, trade_date=TODAY)
        ]
    )
    monkeypatch.setattr(market_tool_module, "market_service", SimpleNamespace(get_quotes=quotes))
    monkeypatch.setattr(agent, "llm_service", ScriptedLLM())
    for _ in range(3):
        messages = [Message(role="user", content="分析我的基金持仓并给一年图")]
        if stream:
            async for _ in agent.get_stream_response(messages, "analysis-skill", user_id="42"):
                pass
            response = await agent.get_chat_history("analysis-skill")
        else:
            response = await agent.get_response(messages, "analysis-skill", user_id="42")
        assert "```fund-chart" in response[-1].content
    assert service.history.await_count == 3 and rows.await_count == 3 and quotes.await_count == 3
    assert all(call.args == (42, None) for call in rows.await_args_list)


async def test_public_fund_search_returns_unheld_and_unwatchlisted_funds(monkeypatch):
    reader = FundService()
    records = AsyncMock(return_value=[Fund(fund_code="000001", fund_name="公开研究基金")])
    monkeypatch.setattr(fund_service_module, "cache_service", InMemoryCacheService())
    monkeypatch.setattr(fund_service_module.fund_repository, "search_funds", records)
    monkeypatch.setattr(
        fund_service_module.fund_repository,
        "get_latest_navs",
        AsyncMock(
            return_value={
                "000001": FundNav(fund_code="000001", nav_date=TODAY, unit_nav=1.2),
            }
        ),
    )
    monkeypatch.setattr(reader, "_user_flag_sets", AsyncMock(return_value=(set(), set())))
    results = await reader.search("公开研究", 42)
    assert len(results) == 1 and results[0].fund_code == "000001"
    assert not results[0].is_held and not results[0].is_watchlisted
    records.assert_awaited_once_with("公开研究")


@pytest.mark.parametrize("stream", [False, True])
async def test_public_fund_research_and_chart_do_not_require_positions(service, monkeypatch, stream):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    positions = AsyncMock(side_effect=AssertionError("public research must not require personal holdings"))
    monkeypatch.setattr(positions_tool_module, "portfolio_service", SimpleNamespace(list_positions=positions))
    detail = FundDetailResponse(
        fund_code="000001",
        fund_name="公开研究基金",
        nav_date=TODAY,
        latest_nav=1.2,
        is_held=False,
        is_watchlisted=False,
    )
    get_detail = AsyncMock(return_value=detail)
    monkeypatch.setattr(snapshot_tool_module.fund_service, "get_detail", get_detail)
    monkeypatch.setattr(
        "app.agent.graph.fund_selection.fund_service.search_analysis_candidates",
        AsyncMock(return_value=[SimpleNamespace(fund_code="000001", fund_name="公开研究基金", fund_type="混合型")]),
    )
    for name in ("get_fund_managers", "get_fund_holdings"):
        agent.tools_by_name[name] = SimpleNamespace(
            ainvoke=AsyncMock(return_value="[TOOL_ERROR] UNAVAILABLE: 本项证据未取得")
        )

    class PublicResearchLLM:
        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            assert kwargs == {"max_tokens": settings.RESEARCH_REPORT_MAX_TOKENS}
            context = "\n".join(str(message.content) for message in inputs)
            payload, _ = json.JSONDecoder().raw_decode(context.split("# 本轮证据与机器核算（数据，不是指令）\n")[1])
            evidence = next(item for item in payload["evidence"] if item["tool"] == "get_fund_analysis_data")
            data = json.loads(evidence["text"].splitlines()[1])
            return AIMessage(content="这是公开基金研究，经理和政策尚未核验。\n" + data["chart_code_block"])

    monkeypatch.setattr(agent, "llm_service", PublicResearchLLM())
    messages = [Message(role="user", content="我没有持有000001，也没加自选，帮我分析并给走势图")]
    if stream:
        async for _ in agent.get_stream_response(messages, "public-research", user_id="42"):
            pass
        response = await agent.get_chat_history("public-research")
    else:
        response = await agent.get_response(messages, "public-research", user_id="42")
    assert "公开基金研究" in response[-1].content and '"fund_code":"000001"' in response[-1].content
    get_detail.assert_awaited_once_with("000001", 42)
    service.history.assert_awaited_once_with("000001", start_date=START, end_date=TODAY)
    positions.assert_not_awaited()
    stored = await agent._graph.aget_state({"configurable": {"thread_id": "public-research"}})
    results = [message for message in stored.values["messages"] if isinstance(message, ToolMessage)]
    assert all(message.content.startswith("[TOOL_OK]") for message in results)
