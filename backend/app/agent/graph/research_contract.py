"""Deterministic per-role assignments; coverage is derived from real citations, not self-reported."""

from typing import Literal, TypedDict

from app.schemas.multi_role_research import (
    AgentAnalysis,
    AgentReport,
    EvidenceFinding,
    EvidenceRequirement,
    ResearchAssignment,
    ResearchRole,
    TaskCoverage,
)
from app.schemas.research import ResearchGraphState

CoverageStatus = Literal["completed", "partial", "blocked", "skipped"]
ReportStatus = Literal["completed", "partial", "failed", "skipped"]


class ManifestTask(TypedDict):
    """一个角色维度的覆盖结论，进报告上下文与结尾附注.

    `role_label` 与 `dropped_citations` 是给成文节点用的：它写某一节时要能直接引用
    中文名和「有几条结论因引用无法核对被排除」，而不是从缺口文字里猜或干脆不提。
    """

    task_id: str
    role: ResearchRole
    role_label: str
    status: CoverageStatus
    attempted: bool
    met: list[str]
    missing: list[str]
    explanation: str
    dropped_citations: int


class CompletionManifest(TypedDict):
    """交给最终成文节点的机器核算结果."""

    tasks: list[ManifestTask]
    required_count: int
    completed_count: int
    review_status: Literal["completed", "partial", "failed"] | None
    revision_required_roles: list[ResearchRole]
    revision_status: dict[ResearchRole, ReportStatus]


# 每个角色只看得见自己那块数据：既省 token，也让「这个角色到底看了什么」可核对。
# 有意留出 get_fund_comparison_data 给业绩与风险共用——两者读的是同一份共同窗口
# 计算结果里的不同字段，拆不开。
_ROLE_TOOLS: dict[ResearchRole, frozenset[str]] = {
    "performance": frozenset(
        {"get_fund_snapshot", "get_fund_benchmark", "get_fund_comparison_data", "get_market_context"}
    ),
    "risk": frozenset({"get_fund_analysis_data", "get_fund_comparison_data"}),
    "holdings": frozenset({"get_fund_holdings", "get_fund_sectors", "get_sector_market"}),
    "manager": frozenset({"get_fund_managers"}),
    "disclosure": frozenset({"get_fund_announcements", "get_market_events"}),
    "portfolio": frozenset(
        {"get_portfolio", "get_portfolio_snapshot", "get_positions", "identify_event_portfolio_links"}
    ),
}

ROLE_LABELS: dict[ResearchRole, str] = {
    "performance": "业绩与基准契合",
    "risk": "风险与回撤",
    "holdings": "持仓与行业风格",
    "manager": "基金经理与团队",
    "disclosure": "披露与来源质量",
    "portfolio": "组合适配",
}

_SKIP_LABELS = {
    "not_applicable": "本轮没有分配该维度的研究任务",
    "no_verified_positions": "个人持仓没有成功取得，组合适配未完成",
    "not_required": "审核未要求该角色修订",
    "previous_failed": "首轮未完成，修订轮跳过",
    "budget": "多角色分析总时限已用尽",
}

_GAP_LABELS = {
    "get_fund_analysis_data": "净值风险指标",
    "get_fund_benchmark": "业绩比较基准",
    "get_fund_comparison_data": "共同窗口数据",
    "get_fund_snapshot": "基金概况",
    "get_fund_holdings": "披露持仓",
    "get_fund_managers": "经理资料",
    "get_fund_announcements": "基金公告",
    "get_market_events": "市场事件",
    "get_market_context": "市场概况",
}


def build_assignments(state: ResearchGraphState) -> list[ResearchAssignment]:
    """每个角色一条任务；任务数不随基金数量膨胀，也不额外调用规划模型."""
    task = state.research_task
    if task is None or task.turn_id != state.turn_id:
        raise ValueError("research assignment scope mismatch")
    comparison = task.request.intent == "fund_comparison"
    assignments = [
        ResearchAssignment(
            task_id="performance",
            role="performance",
            summary=(
                "用分期收益、业绩比较基准原文与构成权重说明这只基金相对它自己声称的基准表现如何；"
                "基准读不懂或成分指数取不到时说明缺口。系统没有同类排名与百分位数据，不要用排名替代。"
            ),
            required_evidence=[
                EvidenceRequirement(label="基金概况与分期收益", tools=["get_fund_snapshot"], scope="per_fund"),
                EvidenceRequirement(label="业绩比较基准", tools=["get_fund_benchmark"], scope="per_fund"),
                *(
                    [EvidenceRequirement(label="共同窗口对比", tools=["get_fund_comparison_data"], scope="global")]
                    if comparison
                    else []
                ),
            ],
        ),
        ResearchAssignment(
            task_id="risk",
            role="risk",
            summary=(
                "用回撤幅度与峰谷日期、年化波动率、夏普与索提诺（无风险利率按0）说明风险特征和结论失效的条件；"
                "指标为空就明确说没算出来，不推断缺失数据。"
            ),
            required_evidence=[
                EvidenceRequirement(
                    label="共同窗口风险指标" if comparison else "净值风险指标",
                    tools=["get_fund_comparison_data"] if comparison else ["get_fund_analysis_data"],
                    scope="global" if comparison else "per_fund",
                )
            ],
        ),
        ResearchAssignment(
            task_id="holdings",
            role="holdings",
            summary=(
                "用披露的前十大重仓与行业配置（含上一季对照、增减仓与新进标记）说明集中度与行业倾斜；"
                "只有前十大且按季披露，不能声称全部持仓或实时仓位。"
            ),
            required_evidence=[
                EvidenceRequirement(label="披露持仓与行业配置", tools=["get_fund_holdings"], scope="per_fund")
            ],
        ),
        ResearchAssignment(
            task_id="manager",
            role="manager",
            summary=(
                "用历任经理区间、任期长度与任职回报原文说明团队稳定性和经理变更风险；"
                "任职回报是整个团队区间的合计，不能拆到个人，也不代表该经理在其他基金的表现。"
            ),
            required_evidence=[
                EvidenceRequirement(label="历任经理与任期", tools=["get_fund_managers"], scope="per_fund")
            ],
        ),
        ResearchAssignment(
            task_id="disclosure",
            role="disclosure",
            summary=(
                "用公告索引（标题、日期、重大变更提示）与市场事件说明近期重大事项和来源时效；"
                "只有标题没有正文，不能把标题当成已经读过的结论，也不能由公告数量推断基金好坏。"
            ),
            required_evidence=[
                EvidenceRequirement(label="公告索引", tools=["get_fund_announcements"], scope="per_fund")
            ],
        ),
    ]
    # 只要本轮**尝试过**读持仓就设这个维度：失败时也要留下「个人持仓没取到」这条
    # 明确披露，而不是让组合适配静默消失，用户以为分析过了。
    if any(item.tool == "get_positions" for item in state.evidence):
        assignments.append(
            ResearchAssignment(
                task_id="portfolio",
                role="portfolio",
                summary=(
                    "只根据已核验的个人持仓与账户范围说明目标基金的组合作用、取舍和条件适配；"
                    "研究的前三只不代表全组合穿透，缺少期限、风险承受或金额时给条件方案，不猜也不自行算金额。"
                ),
                required_evidence=[
                    EvidenceRequirement(
                        label="已核验持仓与账户范围",
                        tools=["get_positions", "get_portfolio_snapshot"],
                        scope="global",
                    )
                ],
            )
        )
    return assignments


def role_evidence(packet: list[dict], role: ResearchRole) -> list[dict]:
    """Keep role-relevant original evidence; product analysis never receives private positions."""
    return [item for item in packet if item["tool"] in _ROLE_TOOLS[role]]


def derive_coverage(
    analysis: AgentAnalysis,
    packet: list[dict],
    assignment: ResearchAssignment,
    fund_codes: list[str],
    issue_indices: list[int],
) -> tuple[AgentAnalysis, TaskCoverage, list[str]]:
    """丢弃引用无效证据的发现，再由代码从存活发现的实际引用推导覆盖.

    模型只负责给结论和引用证据 ID；「这个角色覆盖到了哪些对象、哪些数据维度」由这里算。
    以前要模型自己填 coverage 表并做索引交叉核对，实测 31 次角色输出 0 次 completed，
    每次都是恰好 4 findings + 4 gaps（全撞上限）——那是契约在决定结果，不是分析在决定。
    """
    evidence = {item["evidence_id"]: item for item in packet}
    findings: list[EvidenceFinding] = []
    gaps: list[str] = []
    dropped = 0
    for finding in analysis.findings:
        if set(finding.evidence_ids) <= evidence.keys():
            findings.append(finding)
        else:
            dropped += 1
    if dropped:
        gaps.append(f"有 {dropped} 条结论引用了不存在或该角色不可见的证据，已排除")
    if not findings:
        gaps.append("未产生可核验的研究结论")

    cited = [evidence[evidence_id] for finding in findings for evidence_id in finding.evidence_ids]
    met: list[str] = []
    missing: list[str] = []
    for requirement in assignment.required_evidence:
        hits = [item for item in cited if item["tool"] in requirement.tools]
        if requirement.scope == "per_fund" and fund_codes:
            lacking = [code for code in fund_codes if not any(_matches_fund(item, code) for item in hits)]
            if lacking:
                missing.append(requirement.label + "（缺 " + "、".join(lacking) + "）")
            else:
                met.append(requirement.label)
        elif hits:
            met.append(requirement.label)
        else:
            missing.append(requirement.label)

    # 审核反馈的确认同样由代码核：越界确认（声称回应了没分配给它的 issue）和漏确认都记下来。
    addressed = sorted(set(analysis.addressed_issue_indices) & set(issue_indices))
    if set(issue_indices) - set(addressed):
        gaps.append("尚未回应全部分配给该角色的审核反馈")
    if set(analysis.addressed_issue_indices) - set(issue_indices):
        gaps.append("越界的审核反馈确认已排除")

    status = "blocked" if not findings else "completed" if not missing else "partial"
    explanation = (
        "没有可核验的发现"
        if not findings
        else "已覆盖 " + "、".join(met)
        if not missing
        else "缺少 " + "；".join(missing)
    )
    coverage = TaskCoverage(
        task_id=assignment.task_id,
        status=status,
        met=met,
        missing=missing,
        explanation=explanation,
        dropped_citations=dropped,
    )
    all_gaps = list(dict.fromkeys([*gaps, *analysis.gaps]))
    kept = AgentAnalysis(
        findings=findings,
        # 存进信封的缺口截断到 4 条（schema 上限），但状态判定用的是未截断的 all_gaps。
        gaps=all_gaps[:4],
        addressed_issue_indices=addressed,
    )
    return kept, coverage, all_gaps


def _matches_fund(item: dict, code: str) -> bool:
    """一条证据是否针对这只基金；对比类工具的入参是代码列表."""
    args = item.get("args") or {}
    return args.get("fund_code") == code or code in (args.get("fund_codes") or [])


def selected_reports(state: ResearchGraphState) -> dict[ResearchRole, AgentReport]:
    """Keep valid first-round work when no revision is needed or a revision fails."""
    first: dict[ResearchRole, AgentReport] = {
        item.role: item for item in state.agent_reports if item.run_id == state.turn_id and item.round == 1
    }
    second: dict[ResearchRole, AgentReport] = {
        item.role: item for item in state.agent_reports if item.run_id == state.turn_id and item.round == 2
    }
    return {
        role: second[role] if role in second and second[role].status in {"completed", "partial"} else item
        for role, item in first.items()
    }


def completion_manifest(state: ResearchGraphState) -> CompletionManifest:
    """Expose machine-derived coverage and revision state to the final synthesizer."""
    reports = selected_reports(state)
    assignments = state.agent_assignments or build_assignments(state)
    revisions: dict[ResearchRole, ReportStatus] = {
        item.role: item.status for item in state.agent_reports if item.run_id == state.turn_id and item.round == 2
    }
    tasks: list[ManifestTask] = []
    for item in assignments:
        report = reports.get(item.role)
        label = ROLE_LABELS.get(item.role, item.role)
        if report is not None and report.status == "skipped":
            tasks.append(
                {
                    "task_id": item.task_id,
                    "role": item.role,
                    "role_label": label,
                    "status": "skipped",
                    "attempted": False,
                    "met": [],
                    "missing": [requirement.label for requirement in item.required_evidence],
                    "explanation": _SKIP_LABELS.get(report.skip_reason or "", "该角色未运行"),
                    "dropped_citations": 0,
                }
            )
            continue
        coverage = report.coverage if report is not None else None
        tasks.append(
            {
                "task_id": item.task_id,
                "role": item.role,
                "role_label": label,
                "status": coverage.status if coverage is not None else "blocked",
                "attempted": coverage is not None,
                "met": list(coverage.met) if coverage is not None else [],
                "missing": list(coverage.missing)
                if coverage is not None
                else [requirement.label for requirement in item.required_evidence],
                "explanation": coverage.explanation if coverage is not None else "角色没有产出可核验的发现",
                "dropped_citations": coverage.dropped_citations if coverage is not None else 0,
            }
        )
    running = [item for item in tasks if item["status"] != "skipped"]
    return {
        "tasks": tasks,
        # 未运行的角色不进分母：拿它当分母，界面就会一直显示「6 个角色里 1 个完成」。
        "required_count": len(running),
        "completed_count": sum(item["status"] == "completed" for item in running),
        "review_status": state.agent_review_status,
        "revision_required_roles": state.agent_revision_roles,
        "revision_status": revisions,
    }


def divergences(state: ResearchGraphState) -> list[dict]:
    """服务端算出的跨角色分歧清单，供独立报告节点逐项落笔.

    模型不该自己去"发现"分歧：审核给出的 issues 是结构化的（role + finding_index +
    reason），而"这条有没有被修订回应"同样能从信封里查出来。算好再交给它，报告里的
    分歧段才是可核对的，而不是它读完几段文本后的印象。
    """
    if state.agent_review is None:
        return []
    # 角色在修订轮里回应的是全局 issue 序号（payload 的 required_issue_indices 就是全局序号），
    # 所以"已解决"只看该角色 round=2 且已完成的信封。
    addressed = {
        index
        for report in state.agent_reports
        if report.run_id == state.turn_id and report.round == 2 and report.status in {"completed", "partial"}
        for index in report.analysis.addressed_issue_indices
    }
    return [
        {
            "role": issue.role,
            "finding_index": issue.finding_index,
            "reason": issue.reason,
            "resolved": index in addressed,
        }
        for index, issue in enumerate(state.agent_review.issues)
    ]


def completion_note(state: ResearchGraphState) -> str:
    """Always publish confirmed scope and unmet evidence, even if synthesis omits them."""
    manifest = completion_manifest(state)
    parts = ["\n\n---\n\n**研究范围核对**", "研究对象：" + ("、".join(state.fund_codes) or "无确认对象")]
    for task in manifest["tasks"]:
        label = ROLE_LABELS.get(task["role"], task["role"])
        if task["status"] == "skipped":
            parts.append(label + "：未运行（" + task["explanation"] + "）")
            continue
        if task["status"] == "completed":
            parts.append(label + "：已覆盖 " + "、".join(task["met"]))
            continue
        suffix = "；修订未完成，首轮发现仍待复核" if _revision_pending(state, manifest, task["role"]) else ""
        detail = "缺少 " + "；".join(task["missing"]) if task["missing"] else task["explanation"]
        parts.append(label + "：" + detail + suffix)
    if state.agent_review_status != "completed":
        parts.append("交叉审核：" + ("未完成" if state.agent_review_status == "failed" else "存在待核验项"))
    for gap in state.gaps:
        if "数据范围或质量不完整" in gap or "数据并非最新" in gap:
            for tool, label in _GAP_LABELS.items():
                gap = gap.replace(tool, label)
            parts.append(gap)
    return "\n\n".join(parts)


def _revision_pending(state: ResearchGraphState, manifest: CompletionManifest, role: ResearchRole) -> bool:
    """该角色被要求修订但没修订成功；首轮结论仍在，只是审核反馈没被回应."""
    return role in state.agent_revision_roles and manifest["revision_status"].get(role) in {None, "failed", "skipped"}
