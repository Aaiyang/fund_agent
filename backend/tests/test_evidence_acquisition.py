"""工具元数据解析与按基金取得台账的回归."""

from app.agent.graph.evidence_matrix import build_acquisition, missing_metrics, retry_calls
from app.agent.graph.research import evidence_from_text
from app.agent.tools.result import ToolResult
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask


def state(evidence: list[ResearchEvidence]) -> ResearchGraphState:
    request = ResearchRequest(intent="fund_research", mode="standard", fund_queries=["000001"])
    return ResearchGraphState(
        turn_id="t",
        fund_codes=["000001"],
        research_task=ResearchTask(turn_id="t", request=request, instruction="研究这只基金"),
        evidence=evidence,
    )


def item(name: str, args: dict, result: ToolResult) -> ResearchEvidence:
    return evidence_from_text(name, args, result.to_text())


def test_success_metadata_is_kept_structurally() -> None:
    parsed = item(
        "get_fund_snapshot",
        {"fund_code": "000001"},
        ToolResult.ok(
            {"fund_code": "000001", "latest_nav": 1.2},
            source="akshare",
            as_of="2026-10-21",
            stale=True,
            warnings=["口径提示"],
        ),
    )
    assert parsed.success and parsed.status == "ok"
    assert parsed.source == "akshare" and parsed.as_of == "2026-10-21"
    assert parsed.stale is True and parsed.warnings == ["口径提示"]


def test_success_but_empty_is_recorded_as_empty() -> None:
    parsed = item("get_fund_holdings", {"fund_code": "000001"}, ToolResult.ok({"top_holdings": []}))
    assert parsed.success and parsed.status == "empty"


def test_failure_keeps_error_code_and_retryability() -> None:
    explicit = item(
        "get_fund_benchmark",
        {"fund_code": "000001"},
        ToolResult.fail("UPSTREAM_ERROR", "暂时不可用", retryable=True),
    )
    permanent = item(
        "get_fund_holdings",
        {"fund_code": "000001"},
        ToolResult.fail("DATA_NOT_AVAILABLE", "没有披露"),
    )
    assert explicit.status == "failed" and explicit.error_code == "UPSTREAM_ERROR" and explicit.retryable
    assert permanent.status == "failed" and permanent.error_code == "DATA_NOT_AVAILABLE" and not permanent.retryable


def test_comparison_and_analysis_report_missing_per_fund_metrics() -> None:
    comparison = {
        "rows": [{"fund_code": "000001", "observed_max_drawdown_ratio": None, "annualized_nav_volatility_ratio": None}]
    }
    names, codes = missing_metrics("get_fund_comparison_data", comparison)
    assert names and codes == ["000001"]
    analysis = {
        "fund_code": "000001",
        "raw_count": 100,
        "metrics": {"observed_max_drawdown_ratio": None, "annualized_nav_volatility_ratio": 0.2},
    }
    names, codes = missing_metrics("get_fund_analysis_data", analysis)
    assert names == ["observed_max_drawdown_ratio"] and codes == ["000001"]


def test_acquisition_records_ok_empty_failed_and_not_attempted() -> None:
    snapshot = item("get_fund_snapshot", {"fund_code": "000001"}, ToolResult.ok({"fund_code": "000001"}))
    holdings = item("get_fund_holdings", {"fund_code": "000001"}, ToolResult.ok({"top_holdings": []}))
    benchmark = item(
        "get_fund_benchmark",
        {"fund_code": "000001", "range_key": "3y"},
        ToolResult.fail("UPSTREAM_ERROR", "暂时不可用", retryable=True),
    )
    # 计划里没有 benchmark（standard 档），这里作为额外证据进入台账。
    current = state([snapshot, holdings, benchmark])
    rows = build_acquisition(current)
    by_name = {row.tool: row for row in rows}
    assert by_name["get_fund_snapshot"].status == "ok"
    assert by_name["get_fund_holdings"].status == "empty"
    assert by_name["get_fund_benchmark"].status == "failed"
    assert by_name["get_fund_managers"].status == "not_attempted"
    assert by_name["get_fund_managers"].retryable


def test_retry_only_targets_required_retryable_failures_once() -> None:
    request = ResearchRequest(intent="fund_research", mode="standard", fund_queries=["000001"])
    current = ResearchGraphState(
        turn_id="t",
        fund_codes=["000001"],
        research_task=ResearchTask(turn_id="t", request=request, instruction="研究这只基金"),
        evidence=[
            item(
                "get_fund_benchmark",
                {"fund_code": "000001", "range_key": "3y"},
                ToolResult.fail("UPSTREAM_ERROR", "暂时不可用", retryable=True),
            )
        ],
    )
    rows = build_acquisition(current)
    calls = retry_calls(current, rows)
    assert calls[0] == ("get_fund_benchmark", {"fund_code": "000001", "range_key": "3y"})
    # 失败已有一条尝试记录；再补一次后 attempts 到上限，不再重试。
    current.evidence.append(
        item(
            "get_fund_benchmark",
            {"fund_code": "000001", "range_key": "3y"},
            ToolResult.fail("UPSTREAM_ERROR", "仍然不可用", retryable=True),
        )
    )
    rows = build_acquisition(current)
    assert all(name != "get_fund_benchmark" for name, _ in retry_calls(current, rows))
