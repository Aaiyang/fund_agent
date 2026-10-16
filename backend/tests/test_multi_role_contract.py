"""Coverage cannot cross objects, conceal omitted tasks or invent reviewed completion."""

import json
from collections import Counter
from datetime import timedelta

from annotated_types import MaxLen
from pydantic import BaseModel

from app.agent.graph.multi_role_research import build_multi_role_subgraph, remaining_budget
from app.agent.graph.research_contract import build_assignments, role_evidence, verify_agent_analysis
from app.schemas.multi_role_research import (
    AgentAnalysis,
    AgentReport,
    EvidenceFinding,
    ResearchAssignment,
    ResearchReview,
    TaskCoverage,
)
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask
from app.utils.clock import utc_now


def entry(reference, name, code=None):
    """Reference identifiers and tool arguments are issued by the test server."""
    return {
        "evidence_id": reference,
        "tool": name,
        "args": {"fund_code": code} if code else {},
        "success": True,
        "text": "verified",
    }


def finding(refs):
    """A claim with explicit citations; no financial calculations in the fixture."""
    return EvidenceFinding(claim="条件结论", kind="conditional", evidence_ids=refs, limitation="披露滞后")


def coverage(task_id="risk:000001", refs=None, index=0):
    """Bind coverage to a concrete finding index."""
    return TaskCoverage(
        task_id=task_id,
        status="completed",
        finding_indices=[index],
        evidence_ids=refs or ["ev_a", "ev_b"],
        explanation="已覆盖",
    )


def assignment():
    """Both metrics and holdings must belong to the confirmed share class."""
    return ResearchAssignment(
        task_id="risk:000001",
        role="risk",
        fund_code="000001",
        description="风险",
        required_tool_groups=[["get_fund_analysis_data"], ["get_fund_holdings"]],
    )


def test_same_role_cannot_claim_completion_using_another_funds_holdings():
    packet = [entry("ev_a", "get_fund_analysis_data", "000001"), entry("ev_b", "get_fund_holdings", "000002")]
    analysis, gaps = verify_agent_analysis(
        AgentAnalysis(findings=[finding(["ev_a", "ev_b"])], coverage=[coverage()]), packet, [assignment()], []
    )
    assert analysis.coverage[0].status == "blocked" and gaps


def test_valid_indices_are_remapped_after_a_forged_claim_is_dropped():
    packet = [entry("ev_a", "get_fund_analysis_data", "000001"), entry("ev_b", "get_fund_holdings", "000001")]
    source = AgentAnalysis(findings=[finding(["ev_forged"]), finding(["ev_a", "ev_b"])], coverage=[coverage(index=1)])
    analysis, gaps = verify_agent_analysis(source, packet, [assignment()], [])
    assert len(analysis.findings) == 1 and gaps
    assert analysis.coverage[0].status == "completed" and analysis.coverage[0].finding_indices == [0]
    assert source.coverage[0].finding_indices == [1]  # verification does not mutate checkpoint input


def test_coverage_cannot_reference_unrelated_findings_or_unknown_task_ids():
    packet = [entry("ev_a", "get_fund_analysis_data", "000001"), entry("ev_b", "get_fund_holdings", "000001")]
    source = AgentAnalysis(findings=[finding(["ev_a"])], coverage=[coverage(), coverage(task_id="risk:unknown")])
    analysis, gaps = verify_agent_analysis(source, packet, [assignment()], [])
    assert [item.task_id for item in analysis.coverage] == ["risk:000001"]
    assert analysis.coverage[0].status == "blocked" and gaps


def test_missing_task_and_false_feedback_acknowledgement_are_not_completed():
    packet = [entry("ev_a", "get_fund_analysis_data", "000001")]
    source = AgentAnalysis(findings=[finding(["ev_a"])], addressed_issue_indices=[1])
    analysis, gaps = verify_agent_analysis(source, packet, [assignment()], [0])
    assert analysis.coverage[0].status == "blocked" and analysis.addressed_issue_indices == []
    assert any("审核反馈" in gap for gap in gaps)


def test_explicit_blocked_task_keeps_its_reason_without_fabricating_sources():
    source = AgentAnalysis(
        coverage=[TaskCoverage(task_id="risk:000001", status="blocked", explanation="净值查询失败")]
    )
    analysis, gaps = verify_agent_analysis(source, [], [assignment()], [])
    assert analysis.coverage[0].explanation == "净值查询失败" and gaps
    assert not analysis.coverage[0].evidence_ids


def test_role_packet_excludes_private_positions_and_unrelated_market_prose():
    packet = [entry("a", "get_positions"), entry("b", "get_market_events"), entry("c", "get_fund_snapshot", "000001")]
    assert [item["evidence_id"] for item in role_evidence(packet, "fundamentals")] == ["c"]
    assert len(role_evidence(packet, "risk")) == 3


def test_three_fund_comparison_assigns_every_confirmed_code_and_a_common_window_task():
    codes = ["000001", "000002", "000003"]
    state = ResearchGraphState(
        turn_id="t",
        fund_codes=codes,
        research_task=ResearchTask(
            turn_id="t",
            request=ResearchRequest(intent="fund_comparison", fund_queries=codes, strategy="multi_role"),
            instruction="比较这三只",
        ),
    )
    assignments = build_assignments(state)
    assert {item.fund_code for item in assignments if item.role == "fundamentals" and item.fund_code} == set(codes)
    assert all(["get_fund_comparison_data"] in item.required_tool_groups for item in assignments if item.fund_code)
    assert len([item for item in assignments if item.role == "fundamentals"]) == 4


def test_restored_budget_does_not_restart_the_stage_clock():
    assert remaining_budget(ResearchGraphState(agent_started_at=utc_now() - timedelta(days=1))) == 0


async def test_failed_positions_skip_portfolio_model_but_keep_its_tasks_blocked():
    calls = []

    async def call(prompt, data, schema, config, on_text=None) -> BaseModel:
        calls.append(prompt)
        packet = json.loads(data)
        if schema is ResearchReview:
            return ResearchReview()
        return AgentAnalysis(findings=[finding([packet["evidence"][0]["evidence_id"]])])

    async def fetch(*args):
        raise AssertionError("no supplements requested")

    state = ResearchGraphState(
        turn_id="t",
        fund_codes=["000001"],
        research_task=ResearchTask(
            turn_id="t",
            request=ResearchRequest(intent="fund_research", fund_queries=["000001"], strategy="multi_role"),
            instruction="结合我的持仓分析",
        ),
        evidence=[
            ResearchEvidence(tool="get_positions", success=False, text="[TOOL_ERROR] unavailable"),
            ResearchEvidence(
                tool="get_fund_snapshot", args={"fund_code": "000001"}, success=True, text="[TOOL_OK] snapshot"
            ),
        ],
    )
    graph = build_multi_role_subgraph(call, lambda s: ([item.model_dump() for item in s.evidence], []), fetch)
    result = await graph.ainvoke(state)
    assert not any("组合分析员" in prompt for prompt in calls)
    reports = [AgentReport.model_validate(item) for item in result["agent_reports"]]
    assert (
        next(item for item in reports if item.role == "portfolio" and item.round == 1).skip_reason
        == "no_verified_positions"
    )
    assert any("个人持仓没有成功取得" in gap for gap in result["gaps"])


def test_coverage_capacity_fits_the_largest_assignment_load():
    """Coverage 的上限必须容得下 build_assignments 给单个角色的最多任务数.

    卡在小数字上等于在结构上规定"这个角色必然 partial"——三基金对比时 portfolio
    会拿到每基金一条再加 scope/fit/scenario 三条。
    """
    codes = ["000001", "000002", "000003"]
    state = ResearchGraphState(
        turn_id="t",
        fund_codes=codes,
        research_task=ResearchTask(
            turn_id="t",
            request=ResearchRequest(intent="fund_comparison", fund_queries=codes, strategy="multi_role"),
            instruction="比较这三只",
        ),
    )
    per_role = Counter(item.role for item in build_assignments(state))
    limit = next(arg.max_length for arg in AgentAnalysis.model_fields["coverage"].metadata if isinstance(arg, MaxLen))
    assert max(per_role.values()) <= limit, f"角色任务数 {dict(per_role)} 超过 coverage 上限 {limit}"


def test_skipped_revision_never_erases_a_first_round_verdict():
    """徽标按轮次取后者，但 skipped 只能填空、不能覆盖已出的结论."""
    from app.agent.graph.research import _role_outcomes

    envelopes = [
        AgentReport(run_id="t", role="risk", round=1, status="completed"),
        AgentReport(run_id="t", role="risk", round=2, status="skipped", skip_reason="not_required"),
        AgentReport(run_id="t", role="fundamentals", round=1, status="failed"),
        AgentReport(run_id="t", role="fundamentals", round=2, status="skipped", skip_reason="previous_failed"),
        AgentReport(run_id="t", role="portfolio", round=1, status="skipped", skip_reason="no_verified_positions"),
    ]
    assert _role_outcomes("t", envelopes) == {"risk": "completed", "fundamentals": "failed", "portfolio": "skipped"}
