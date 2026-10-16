"""Coverage is derived from real citations; it cannot cross objects or be self-declared."""

import json
from collections import Counter
from datetime import timedelta

from annotated_types import MaxLen
from pydantic import BaseModel

from app.agent.graph.multi_role_research import build_multi_role_subgraph, remaining_budget
from app.agent.graph.research_contract import build_assignments, completion_note, derive_coverage, role_evidence
from app.schemas.multi_role_research import (
    AgentAnalysis,
    AgentReport,
    EvidenceFinding,
    EvidenceRequirement,
    ResearchAssignment,
    ResearchReview,
    TaskCoverage,
)
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask
from app.utils.clock import utc_now


def entry(reference, name, code=None):
    """Reference identifiers and tool arguments are issued by the test server, never the model."""
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


def risk_assignment():
    """Metrics and holdings both have to belong to each confirmed share class."""
    return ResearchAssignment(
        task_id="risk",
        role="risk",
        summary="风险",
        required_evidence=[
            EvidenceRequirement(label="净值风险指标", tools=["get_fund_analysis_data"], scope="per_fund"),
            EvidenceRequirement(label="披露持仓", tools=["get_fund_holdings"], scope="per_fund"),
        ],
    )


PACKET = [entry("ev_a", "get_fund_analysis_data", "000001"), entry("ev_b", "get_fund_holdings", "000001")]


def derive(analysis, packet=PACKET, assignment=None, codes=("000001",), issues=()):
    return derive_coverage(analysis, packet, assignment or risk_assignment(), list(codes), list(issues))


class TestDerivedCoverage:
    def test_fully_cited_findings_can_reach_completed(self) -> None:
        """回归"31 次角色输出 0 次 completed"：完整引用必须能走到 completed.

        旧契约要模型自己填 coverage 表并做索引交叉核对，任务数还随基金数膨胀，
        数学上几乎不可满足。现在覆盖由代码从引用反推，引全了就是 completed。
        """
        analysis = AgentAnalysis(findings=[finding(["ev_a"]), finding(["ev_b"])])
        kept, coverage, gaps = derive(analysis)
        assert coverage.status == "completed" and coverage.met == ["净值风险指标", "披露持仓"]
        assert coverage.missing == [] and not gaps and len(kept.findings) == 2

    def test_citation_for_another_share_class_does_not_cover_this_one(self) -> None:
        packet = [entry("ev_a", "get_fund_analysis_data", "000001"), entry("ev_b", "get_fund_holdings", "000002")]
        _, coverage, gaps = derive(AgentAnalysis(findings=[finding(["ev_a", "ev_b"])]), packet)
        # 引用都真实存在，所以服务端缺口为空；缺的是哪块数据由 coverage.missing 说。
        assert coverage.status == "partial" and coverage.missing == ["披露持仓（缺 000001）"] and not gaps

    def test_per_fund_gap_names_every_uncovered_object(self) -> None:
        codes = ["000001", "000002", "000003"]
        packet = [entry(f"ev_f{index}", "get_fund_analysis_data", code) for index, code in enumerate(codes)]
        packet.append(entry("ev_h1", "get_fund_holdings", "000001"))
        # 一条发现只引到 000001 的两块数据：另外两只既没有风险指标也没有持仓。
        _, coverage, _ = derive(AgentAnalysis(findings=[finding(["ev_f0", "ev_h1"])]), packet, codes=codes)
        assert coverage.status == "partial"
        assert coverage.missing == ["净值风险指标（缺 000002、000003）", "披露持仓（缺 000002、000003）"]

    def test_forged_citation_is_dropped_and_buys_no_coverage(self) -> None:
        source = AgentAnalysis(findings=[finding(["ev_forged", "ev_b"])])
        kept, coverage, gaps = derive(source)
        assert kept.findings == [] and coverage.status == "blocked" and gaps
        assert "已排除" in gaps[0]
        assert coverage.missing == ["净值风险指标（缺 000001）", "披露持仓（缺 000001）"]

    def test_no_findings_is_blocked_with_a_reason(self) -> None:
        _, coverage, gaps = derive(AgentAnalysis())
        assert coverage.status == "blocked" and coverage.explanation == "没有可核验的发现"
        assert "未产生可核验的研究结论" in gaps

    def test_model_gaps_are_kept_but_truncated(self) -> None:
        """信封里留 4 条缺口，状态判定看未截断的全量."""
        analysis = AgentAnalysis(
            findings=[finding(["ev_a", "ev_b"]), finding(["ev_forged"])],
            gaps=["近一年净值缺口", "公告仅索引", "行业配置滞后", "经理任职回报缺失"],
        )
        kept, coverage, gaps = derive(analysis)
        # 服务端加的「已排除」排在模型自述之前，合起来 5 条只留 4 条。
        assert coverage.status == "completed" and len(kept.gaps) == 4 and len(gaps) == 5

    def test_out_of_range_feedback_acknowledgement_is_dropped(self) -> None:
        analysis = AgentAnalysis(findings=[finding(["ev_a", "ev_b"])], addressed_issue_indices=[1])
        kept, _, gaps = derive(analysis, issues=[0])
        assert kept.addressed_issue_indices == []
        assert any("越界" in gap for gap in gaps) and any("尚未回应" in gap for gap in gaps)

    def test_global_scope_accepts_any_hit_but_still_requires_citation(self) -> None:
        assignment = ResearchAssignment(
            task_id="risk",
            role="risk",
            summary="风险",
            required_evidence=[
                EvidenceRequirement(label="共同窗口风险指标", tools=["get_fund_comparison_data"], scope="global")
            ],
        )
        codes = ["000001", "000002"]
        packet = [entry(f"ev_c{index}", "get_fund_comparison_data", code) for index, code in enumerate(codes)]
        _, hit, _ = derive(AgentAnalysis(findings=[finding(["ev_c0"])]), packet, assignment, codes)
        _, miss, _ = derive(AgentAnalysis(findings=[finding(["ev_a", "ev_b"])]), PACKET, assignment, codes)
        assert hit.status == "completed" and hit.met == ["共同窗口风险指标"]
        assert miss.status == "partial" and miss.missing == ["共同窗口风险指标"]


class TestRoleEvidenceSlices:
    def test_slices_follow_the_evaluation_dimensions(self) -> None:
        packet = [
            entry("a", "get_positions"),
            entry("b", "get_market_events"),
            entry("c", "get_fund_snapshot", "000001"),
            entry("d", "get_fund_holdings", "000001"),
            entry("e", "get_fund_managers", "000001"),
        ]
        assert [item["evidence_id"] for item in role_evidence(packet, "performance")] == ["c"]
        assert [item["evidence_id"] for item in role_evidence(packet, "holdings")] == ["d"]
        assert [item["evidence_id"] for item in role_evidence(packet, "manager")] == ["e"]
        assert [item["evidence_id"] for item in role_evidence(packet, "disclosure")] == ["b"]
        assert [item["evidence_id"] for item in role_evidence(packet, "portfolio")] == ["a"]

    def test_private_positions_never_reach_a_product_dimension(self) -> None:
        private = [entry("a", "get_positions"), entry("b", "get_fund_analysis_data", "000001")]
        assert [item["evidence_id"] for item in role_evidence(private, "risk")] == ["b"]
        assert [item["evidence_id"] for item in role_evidence(private, "portfolio")] == ["a"]


def comparison_state(codes: list[str]) -> ResearchGraphState:
    return ResearchGraphState(
        turn_id="t",
        fund_codes=codes,
        research_task=ResearchTask(
            turn_id="t",
            request=ResearchRequest(intent="fund_comparison", fund_queries=codes, strategy="multi_role"),
            instruction="比较这些基金",
        ),
    )


class TestAssignmentsDoNotScaleWithObjects:
    def test_task_count_is_flat_in_fund_count(self) -> None:
        """任务不再按「基金 × 角色」展开——那是 0/31 completed 的结构成因."""
        one = build_assignments(comparison_state(["000001", "000002"]))
        three = build_assignments(comparison_state(["000001", "000002", "000003"]))
        assert len(one) == len(three) == 5
        assert {item.task_id for item in three} == {
            "performance",
            "risk",
            "holdings",
            "manager",
            "disclosure",
        }

    def test_requirements_always_fit_the_coverage_capacity(self) -> None:
        """证据要求条数必须容得下 TaskCoverage 的 met/missing 上限，否则又变成必然 partial."""
        limit = min(arg.max_length for arg in TaskCoverage.model_fields["met"].metadata if isinstance(arg, MaxLen))
        largest = max(
            len(item.required_evidence) for item in build_assignments(comparison_state(["000001", "000002"]))
        )
        assert largest <= limit, f"单角色证据要求 {largest} 条超过覆盖结论上限 {limit}"

    def test_per_object_gaps_are_still_enumerated_per_fund(self) -> None:
        codes = ["000001", "000002", "000003"]
        performance = next(item for item in build_assignments(comparison_state(codes)) if item.role == "performance")
        assert [item.scope for item in performance.required_evidence] == ["per_fund", "per_fund", "global"]
        assert Counter(item.role for item in build_assignments(comparison_state(codes))).most_common(1)[0][1] == 1


def test_restored_budget_does_not_restart_the_stage_clock():
    assert remaining_budget(ResearchGraphState(agent_started_at=utc_now() - timedelta(days=1))) == 0


async def test_failed_positions_skip_portfolio_model_but_stay_disclosed():
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
    assert not any("组合配置顾问" in prompt for prompt in calls)
    reports = [AgentReport.model_validate(item) for item in result["agent_reports"]]
    assert (
        next(item for item in reports if item.role == "portfolio" and item.round == 1).skip_reason
        == "no_verified_positions"
    )
    assert any("个人持仓没有成功取得" in gap for gap in result["gaps"])


def test_skipped_revision_never_erases_a_first_round_verdict():
    """徽标按轮次取后者，但 skipped 只能填空、不能覆盖已出的结论."""
    from app.agent.graph.research import _role_outcomes

    envelopes = [
        AgentReport(run_id="t", role="risk", round=1, status="completed"),
        AgentReport(run_id="t", role="risk", round=2, status="skipped", skip_reason="not_required"),
        AgentReport(run_id="t", role="manager", round=1, status="failed"),
        AgentReport(run_id="t", role="manager", round=2, status="skipped", skip_reason="previous_failed"),
        AgentReport(run_id="t", role="portfolio", round=1, status="skipped", skip_reason="no_verified_positions"),
    ]
    assert _role_outcomes("t", envelopes) == {"risk": "completed", "manager": "failed", "portfolio": "skipped"}


def test_report_footer_states_coverage_positively_when_met():
    """附注先说覆盖了什么；只有缺项才逐条列缺口.

    旧附注在 11/11 次运行里都是一串「待完成」，让正常的报告看起来像坏掉了。
    """
    assignment = ResearchAssignment(
        task_id="performance",
        role="performance",
        summary="业绩",
        required_evidence=[EvidenceRequirement(label="基金概况与分期收益", tools=["get_fund_snapshot"])],
    )
    state = ResearchGraphState(
        turn_id="t",
        fund_codes=["000001"],
        agent_assignments=[assignment],
        agent_review_status="completed",
        agent_reports=[
            AgentReport(
                run_id="t",
                role="performance",
                round=1,
                status="completed",
                coverage=TaskCoverage(
                    task_id="performance",
                    status="completed",
                    met=["基金概况与分期收益"],
                    explanation="已覆盖 基金概况与分期收益",
                ),
            )
        ],
    )
    note = completion_note(state)
    assert "业绩与基准契合：已覆盖 基金概况与分期收益" in note
    assert "缺少" not in note and "待完成" not in note
