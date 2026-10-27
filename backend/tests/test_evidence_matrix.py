"""取证矩阵的 intent × fund 计划与角色必需证据回归."""

from app.agent.graph.evidence_matrix import plan_calls, required_calls, tool_args
from app.schemas.research import ResearchGraphState, ResearchRequest, ResearchTask


def state(
    intent: str,
    *,
    mode: str = "standard",
    codes: list[str] | None = None,
    instruction: str = "研究这只基金",
    **request_kwargs,
) -> ResearchGraphState:
    codes = codes or []
    request = ResearchRequest(
        intent=intent,
        mode=mode,
        strategy="multi_role" if intent not in {"sector_research", "stock_research"} else "single",
        fund_queries=codes,
        **request_kwargs,
    )
    return ResearchGraphState(
        turn_id="t",
        fund_codes=codes,
        research_task=ResearchTask(turn_id="t", request=request, instruction=instruction),
    )


def test_stock_standard_plan_is_only_stock_data() -> None:
    calls = plan_calls(state("stock_research", stock_symbol="sh600519"))
    assert [call.name for call in calls] == ["get_stock_analysis_data"]
    assert calls[0].args == {"symbol": "sh600519"}


def test_sector_standard_plan_adds_market_context() -> None:
    calls = plan_calls(state("sector_research", sector_query="半导体"))
    assert [call.name for call in calls] == ["get_sector_market", "get_market_context", "get_market_events"]


def test_fund_research_standard_plan_per_fund_order() -> None:
    calls = plan_calls(state("fund_research", codes=["000001"]))
    assert [(call.name, call.args) for call in calls] == [
        ("get_fund_snapshot", {"fund_code": "000001"}),
        ("get_fund_analysis_data", {"fund_code": "000001"}),
        ("get_fund_holdings", {"fund_code": "000001"}),
        ("get_fund_managers", {"fund_code": "000001", "limit": 10}),
    ]


def test_portfolio_standard_skips_managers() -> None:
    calls = plan_calls(state("portfolio_diagnosis", codes=["000001"]))
    assert [call.name for call in calls] == [
        "get_fund_snapshot",
        "get_fund_analysis_data",
        "get_fund_holdings",
    ]


def test_comparison_deep_has_one_global_comparison_and_no_analysis_per_fund() -> None:
    calls = plan_calls(state("fund_comparison", mode="deep", codes=["000001", "000002", "000003"]))
    names = [call.name for call in calls]
    assert names.count("get_fund_comparison_data") == 1
    assert "get_fund_analysis_data" not in names
    assert names[0] == "get_fund_comparison_data"
    assert names.count("get_fund_benchmark") == 3
    assert names.count("get_fund_sectors") == 3
    assert names[-2:] == ["get_market_context", "get_market_events"]


def test_role_calls_keep_requirement_order_and_comparison_scope() -> None:
    current = state("fund_comparison", mode="deep", codes=["000001", "000002"])
    calls = required_calls(current)
    assert [(call.role, call.requirement, call.name) for call in calls[:4]] == [
        ("performance", "基金概况与分期收益", "get_fund_snapshot"),
        ("performance", "基金概况与分期收益", "get_fund_snapshot"),
        ("performance", "业绩比较基准", "get_fund_benchmark"),
        ("performance", "业绩比较基准", "get_fund_benchmark"),
    ]
    risk = [call for call in calls if call.role == "risk"]
    assert len(risk) == 1 and risk[0].name == "get_fund_comparison_data"
    assert risk[0].args == {"fund_codes": ["000001", "000002"]}


def test_tool_args_are_shared_by_plan_and_role_topups() -> None:
    current = state("fund_research", codes=["000001"])
    assert tool_args("get_fund_managers", "000001", current) == {"fund_code": "000001", "limit": 10}
    assert tool_args("get_fund_comparison_data", None, current) is None
    assert tool_args("unknown_tool", "000001", current) is None
