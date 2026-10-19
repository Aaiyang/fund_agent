"""Coverage is derived from real citations; it cannot cross objects or be self-declared."""

import json
from collections import Counter
from datetime import timedelta
from typing import Literal

from annotated_types import MaxLen
from pydantic import BaseModel

from app.agent.graph.multi_role_research import build_multi_role_subgraph, remaining_budget
from app.agent.graph.research import report_context
from app.agent.graph.research_contract import (
    build_assignments,
    completion_manifest,
    completion_note,
    derive_coverage,
    role_evidence,
    role_tensions,
)
from app.agent.prompts.graph import ROLE_BRIEFS
from app.agent.roles import ROLE_LABELS, ROLE_OWNERS, section_heading
from app.schemas.multi_role_research import (
    AgentAnalysis,
    AgentReport,
    DimensionStance,
    EvidenceFinding,
    EvidenceRequirement,
    ResearchAssignment,
    ResearchReview,
    ResearchRole,
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
        # 信封里截到 4 条；服务端判定的缺陷只有伪造那 1 条，它才参与状态判定。
        assert (
            coverage.status == "completed"
            and len(kept.gaps) == 4
            and gaps == ["有 1 条结论引用了不存在或该角色不可见的证据，已排除"]
        )

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


def _state_for_report(
    strategy: Literal["single", "multi_role"], coverage: TaskCoverage | None = None
) -> ResearchGraphState:
    """一份能直接喂给 report_context 的最小多角色/单档状态."""
    intent = "fund_research"
    return ResearchGraphState(
        turn_id="t",
        fund_codes=["000001"],
        skill_instructions="内置流程",
        skill_evidence="取证边界",
        research_task=ResearchTask(
            turn_id="t",
            request=ResearchRequest(intent=intent, fund_queries=["000001"], strategy=strategy),
            instruction="研究这只基金",
        ),
        agent_assignments=build_assignments(
            ResearchGraphState(
                turn_id="t",
                fund_codes=["000001"],
                research_task=ResearchTask(
                    turn_id="t",
                    request=ResearchRequest(intent=intent, fund_queries=["000001"], strategy="multi_role"),
                    instruction="研究这只基金",
                ),
            )
        ),
        agent_reports=[
            AgentReport(
                run_id="t",
                role="manager",
                round=1,
                status="partial",
                analysis=AgentAnalysis(findings=[finding(["ev_a"])]),
                coverage=coverage,
            )
        ],
    )


def test_multi_role_report_is_organised_by_dimension_then_synthesis() -> None:
    """多角色报告按维度分节、末尾才综合；这段结构契约必须真的进到成文上下文."""
    context = report_context(_state_for_report("multi_role"))
    assert "每个**实际运行过的**维度单独一节" in context
    assert "综合结论与分歧" in context and "角色分歧与未解决项" in context
    # 关键约束：本维度没覆盖的对象不许借别的维度填空。
    assert "不许借用其他维度的材料填空" in context
    assert "role_label" in context and "dropped_citations" in context


def test_report_sections_are_signed_and_free_of_internal_keys() -> None:
    """每一节由谁写的要能看出来，内部键名不能漏进用户读的正文."""
    context = report_context(_state_for_report("multi_role"))
    assert "节标题逐字复制 completion[].heading" in context
    assert "### 风险分析师｜风险与回撤" in context, "示例抬头要真的出现在契约里，模型才有可抄的形状"
    assert "指称某个维度或同伴时只能用它的中文归属名" in context
    for key in ("performance", "finding_index", "task_id", "partial"):
        assert key in context, f"禁词清单里必须点名 {key}"
    # 综合段的归属写法：署名不是证据。
    assert "同事的署名不是证据" in context


def test_report_structure_restores_the_action_table_and_chart() -> None:
    """多角色曾经比单档更不可执行：行动表与走势图引用都丢了，这里钉回来."""
    context = report_context(_state_for_report("multi_role"))
    assert "行动建议与触发条件" in context
    assert "| --- |" in context, "移动端只认带分隔行的表格语法"
    assert "触发条件" in context and "复核指标" in context
    assert "chart_code_block" in context and "本轮无图表引用" in context


def test_role_vocabulary_has_one_source() -> None:
    """维度名、归属人、简报开头的职务名必须是同一套键与同一批字."""
    from typing import get_args

    roles = set(get_args(ResearchRole))
    assert set(ROLE_LABELS) == roles and set(ROLE_OWNERS) == roles and set(ROLE_BRIEFS) == roles
    assert len(set(ROLE_LABELS.values())) == len(roles) and len(set(ROLE_OWNERS.values())) == len(roles)
    for role, brief in ROLE_BRIEFS.items():
        assert brief.startswith(ROLE_OWNERS[role]), f"{role} 的简报开头与归属人词表漂移了"
    assert section_heading("risk") == f"### {ROLE_OWNERS['risk']}｜{ROLE_LABELS['risk']}"


def test_single_mode_report_keeps_its_own_structure() -> None:
    """维度分节只属于多角色：把新排版漏进单档会连带改掉普通研究的结论先行."""
    context = report_context(_state_for_report("single"))
    assert "综合结论与分歧" not in context and "每个**实际运行过的**维度单独一节" not in context
    assert "行动建议与触发条件" not in context and "｜" not in context
    assert "本轮已由代码完成有界取证" in context


def test_manifest_names_labels_and_reports_dropped_citations() -> None:
    """成文节点要能直接读到中文维度名与被排除的伪引用条数，而不是从缺口文字里猜."""
    coverage = TaskCoverage(
        task_id="manager",
        status="partial",
        met=["历任经理与任期"],
        missing=["历任经理与任期（缺 000001）"],
        explanation="缺少 历任经理与任期（缺 000001）",
        dropped_citations=2,
    )
    # 只 manager 有信封，其余维度既没运行也没覆盖结论。
    manifest = completion_manifest(_state_for_report("multi_role", coverage))
    task = next(item for item in manifest["tasks"] if item["role"] == "manager")
    assert task["role_label"] == "基金经理与团队"
    assert task["role_owner"] == "基金经理研究员"
    assert task["heading"] == "### 基金经理研究员｜基金经理与团队"
    assert task["attempted"] is True and task["dropped_citations"] == 2
    quiet = next(item for item in manifest["tasks"] if item["role"] == "risk")
    assert quiet["attempted"] is False and quiet["status"] == "blocked"
    assert quiet["dropped_citations"] == 0 and quiet["role_label"] == "风险与回撤"
    assert quiet["heading"] == "### 风险分析师｜风险与回撤", "没跑成的维度也要有归属，否则那一节没人认领"


def test_model_stated_limitations_do_not_demote_the_dimension() -> None:
    """真实跑一次才暴露的门：五个维度尾注全「已覆盖」，五个信封却都报 partial.

    模型如实声明的数据局限（系统没有同类排名、公告只有标题）是脚注。把它当缺陷判，
    每次深度研究都必然 partial——和上一轮"任务数超过 findings 上限"是同一类错误。
    """
    analysis = AgentAnalysis(
        findings=[finding(["ev_a"]), finding(["ev_b"])],
        gaps=["系统没有同类排名与百分位数据", "公告仅有标题未读正文", "净值未复权不等于总回报", "持仓按季披露有滞后"],
    )
    kept, coverage, hard_gaps = derive(analysis)
    assert coverage.status == "completed" and kept.gaps, "局限本身仍要留在报告里披露"
    assert hard_gaps == [], "模型自述的局限不能变成服务端缺陷"


def test_stance_never_demotes_the_dimension() -> None:
    """立场只是署名与对照的素材：带对立立场和不带立场，状态判定必须逐字段相同.

    这是本项目栽过两次的坑（任务数超过 findings 上限、把自述局限当缺陷）。任何由模型
    自己填的东西一旦参与状态，就会变成一扇每次运行都过不去的门。
    """
    base = AgentAnalysis(findings=[finding(["ev_a"]), finding(["ev_b"])])
    opposed = base.model_copy(
        update={
            "stance": DimensionStance(
                verdict="按这个回撤水平只宜当卫星仓位",
                marker="oppose",
                topic="position_size",
                condition="回撤收窄到三成内则转为支持",
                evidence_ids=["ev_a"],
            )
        }
    )
    kept_plain, coverage_plain, gaps_plain = derive(base)
    kept, coverage, gaps = derive(opposed)
    assert kept.stance is not None and kept.stance.marker == "oppose", "立场要活着进信封"
    assert coverage == coverage_plain and gaps == gaps_plain, "立场不得改变覆盖结论或服务端缺陷"
    assert kept.findings == base.findings and kept.gaps == base.gaps


def test_stance_citing_unseen_evidence_is_dropped_alone() -> None:
    """立场引了不存在的证据：只丢这个观点，发现与状态都不受牵连."""
    analysis = AgentAnalysis(
        findings=[finding(["ev_a"])],
        stance=DimensionStance(
            verdict="基准读不懂就别谈超额", marker="support", topic="benchmark_fit", evidence_ids=["ev_zzz"]
        ),
    )
    kept, coverage, gaps = derive(analysis)
    assert kept.stance is None
    assert coverage.status == "partial" and len(kept.findings) == 1 and gaps == []


def stance_report(role, marker, topic, verdict, *, fund_code=None, round_number=1):
    """一个带立场的信封，用于配对测试；结论本身不参与配对，只有 stance 参与."""
    return AgentReport(
        run_id="t",
        role=role,
        round=round_number,
        status="completed",
        analysis=AgentAnalysis(
            findings=[finding(["ev_a"])],
            stance=DimensionStance(
                verdict=verdict, marker=marker, topic=topic, fund_code=fund_code, evidence_ids=["ev_a"]
            ),
        ),
    )


def tension_state(*reports):
    return ResearchGraphState(turn_id="t", fund_codes=["000001"], agent_reports=list(reports))


def test_role_tensions_pair_only_strict_opposition() -> None:
    """对立由代码配对：方向必须严格相反、议题与对象都要相同，同角色不配."""
    agree = tension_state(
        stance_report("risk", "oppose", "position_size", "只宜小仓位"),
        stance_report("performance", "conditional", "position_size", "能扛回撤就可以"),
    )
    assert role_tensions(agree) == [], "有条件支持不是反对"
    cross_object = tension_state(
        stance_report("risk", "oppose", "position_size", "只宜小仓位", fund_code="000001"),
        stance_report("performance", "support", "position_size", "可以重仓", fund_code="000002"),
    )
    assert role_tensions(cross_object) == [], "不同对象的不算同一场争论"
    clash = tension_state(
        stance_report("risk", "oppose", "position_size", "只宜小仓位"),
        stance_report("performance", "support", "position_size", "可以按纪律加仓"),
    )
    rows = role_tensions(clash)
    assert len(rows) == 1
    row = rows[0]
    assert (row["owner_a"], row["owner_b"]) == ("业绩分析师", "风险分析师"), "配对顺序按角色键定，重放必须一致"
    assert row["topic_label"] == "仓位大小" and row["revised"] is False and row["evidence_ids"] == ["ev_a"]
    revised = tension_state(
        stance_report("risk", "oppose", "position_size", "只宜小仓位"),
        stance_report("performance", "support", "position_size", "可以按纪律加仓"),
        stance_report("performance", "support", "position_size", "修订后仍支持", round_number=2),
    )
    assert role_tensions(revised)[0]["revised"] is True


def test_role_tensions_ignore_the_catch_all_topic() -> None:
    """兜底枚举 other 不参与配对：配出来的对立不可信."""
    state = tension_state(
        stance_report("risk", "oppose", "other", "这个维度不看好"),
        stance_report("performance", "support", "other", "这个维度看好"),
    )
    assert role_tensions(state) == []


def test_report_structure_requires_an_honest_tension_section() -> None:
    """立场小节要真的进契约，并写明"空也要说实话"."""
    context = report_context(_state_for_report("multi_role"))
    assert "同事立场与分歧" in context and "tensions" in context
    assert "不得为了显得有团队而编造分歧" in context
    assert "stance、marker、topic" in context, "枚举原值也要进禁词清单"


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
