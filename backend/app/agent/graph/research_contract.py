"""Deterministic role assignments and verification of object-scoped task coverage."""

from app.schemas.multi_role_research import AgentAnalysis, AgentReport, ResearchAssignment, ResearchRole, TaskCoverage
from app.schemas.research import ResearchGraphState

_FUND_TOOLS = {
    "get_fund_snapshot",
    "get_fund_analysis_data",
    "get_fund_comparison_data",
    "get_fund_holdings",
    "get_fund_managers",
    "get_fund_announcements",
}
_ROLE_TOOLS = {
    "fundamentals": _FUND_TOOLS,
    "risk": _FUND_TOOLS
    | {
        "get_fund_sectors",
        "get_sector_market",
        "get_market_context",
        "get_market_events",
        "get_portfolio",
        "get_positions",
        "identify_event_portfolio_links",
    },
    "portfolio": _FUND_TOOLS
    | {
        "get_portfolio",
        "get_positions",
        "get_market_context",
        "get_market_events",
        "identify_event_portfolio_links",
    },
}


def build_assignments(state: ResearchGraphState) -> list[ResearchAssignment]:
    """Assign bounded tasks from the confirmed request; no extra planner model call."""
    task = state.research_task
    if task is None or task.turn_id != state.turn_id:
        raise ValueError("research assignment scope mismatch")
    comparison = task.request.intent == "fund_comparison"
    metrics = "get_fund_comparison_data" if comparison else "get_fund_analysis_data"
    result: list[ResearchAssignment] = []
    for code in state.fund_codes:
        result.extend(
            [
                ResearchAssignment(
                    task_id="fundamentals:" + code,
                    role="fundamentals",
                    fund_code=code,
                    description="覆盖该基金策略、历史表现、经理和披露持仓；引用真实口径与日期，不归因或预测。",
                    required_tool_groups=[
                        ["get_fund_snapshot"],
                        [metrics],
                        ["get_fund_managers"],
                        ["get_fund_holdings"],
                    ],
                ),
                ResearchAssignment(
                    task_id="risk:" + code,
                    role="risk",
                    fund_code=code,
                    description="覆盖该基金回撤/波动证据、披露集中度和结论失效条件；缺失指标明确说明。",
                    required_tool_groups=[[metrics], ["get_fund_holdings"]],
                ),
            ]
        )
    result.append(
        ResearchAssignment(
            task_id="risk:source_quality",
            role="risk",
            description="核验来源时效、缺口及分析范围；区分事实、推断与无法验证的内容。",
        )
    )
    if comparison:
        result.append(
            ResearchAssignment(
                task_id="fundamentals:comparison",
                role="fundamentals",
                description="全部确认对象都有对比位置，量化只用共同窗口；未知目标给条件结论，不强制排名。",
                required_tool_groups=[["get_fund_comparison_data"]],
            )
        )
    personal = any(item.tool == "get_positions" for item in state.evidence)
    if personal:
        result.extend(
            [
                ResearchAssignment(
                    task_id="portfolio:scope",
                    role="portfolio",
                    description="核验账户范围与组合账本；研究的前三只不代表全组合穿透。",
                    required_tool_groups=[["get_positions"], ["get_portfolio"]],
                ),
                ResearchAssignment(
                    task_id="portfolio:fit",
                    role="portfolio",
                    description="根据已核验账本说明目标基金的组合作用、取舍和条件适配；不猜风险偏好和金额。",
                    required_tool_groups=[["get_positions"]],
                ),
            ]
        )
        if task.request.intent == "allocation_analysis":
            result.append(
                ResearchAssignment(
                    task_id="portfolio:scenario",
                    role="portfolio",
                    description="对照代码计算的维持/调整/暂缓情景；情景不可用则声明阻塞，禁止自行算金额。",
                    required_tool_groups=[["get_positions"], ["get_portfolio"]],
                )
            )
    return result


def role_evidence(packet: list[dict], role: ResearchRole) -> list[dict]:
    """Keep role-relevant original evidence; product analysis never receives private positions."""
    return [item for item in packet if item["tool"] in _ROLE_TOOLS[role]]


def verify_agent_analysis(
    analysis: AgentAnalysis,
    packet: list[dict],
    assignments: list[ResearchAssignment],
    issue_indices: list[int],
) -> tuple[AgentAnalysis, list[str]]:
    """Validate citations, finding indices, coverage sources and reviewer acknowledgements."""
    evidence = {item["evidence_id"]: item for item in packet}
    findings = []
    index_map: dict[int, int] = {}
    gaps = list(analysis.gaps)
    for index, finding in enumerate(analysis.findings):
        if not set(finding.evidence_ids).issubset(evidence):
            gaps.append("部分结论引用不存在或该角色不可见的证据，已排除")
            continue
        index_map[index] = len(findings)
        findings.append(finding)
    if not findings:
        gaps.append("未产生可核验的研究结论")
    coverage: dict[str, TaskCoverage] = {}
    expected = {item.task_id: item for item in assignments}
    for item in analysis.coverage:
        if item.task_id not in expected or item.task_id in coverage:
            gaps.append("未知或重复的任务覆盖记录已排除")
            continue
        assignment = expected[item.task_id]
        indices = list(dict.fromkeys(item.finding_indices))
        refs = set(item.evidence_ids)
        valid = bool(indices and refs) and all(index in index_map for index in indices)
        cited = {ref for index in indices if index in index_map for ref in analysis.findings[index].evidence_ids}
        valid = valid and refs.issubset(cited) and refs.issubset(evidence)
        matching = []
        for ref in refs & evidence.keys():
            entry = evidence[ref]
            args = entry.get("args", {})
            if (
                assignment.fund_code is None
                or assignment.fund_code == args.get("fund_code")
                or (assignment.fund_code in args.get("fund_codes", []))
            ):
                matching.append(entry["tool"])
        valid = valid and all(any(tool in matching for tool in group) for group in assignment.required_tool_groups)
        if item.status == "completed" and valid:
            coverage[item.task_id] = item.model_copy(
                update={"finding_indices": [index_map[index] for index in indices]}
            )
        else:
            coverage[item.task_id] = TaskCoverage(
                task_id=item.task_id,
                status="blocked",
                explanation=item.explanation if item.status == "blocked" else "引用或发现未满足任务的对象与证据要求",
            )
    for assignment in assignments:
        coverage.setdefault(
            assignment.task_id,
            TaskCoverage(
                task_id=assignment.task_id,
                status="blocked",
                explanation="未报告该研究项的覆盖情况",
            ),
        )
    for item in coverage.values():
        if item.status != "completed":
            gaps.append(item.task_id + "：" + item.explanation)
    addressed = sorted(set(analysis.addressed_issue_indices) & set(issue_indices))
    if set(issue_indices) - set(addressed):
        gaps.append("尚未回应全部分配给该角色的审核反馈")
    if set(analysis.addressed_issue_indices) - set(issue_indices):
        gaps.append("越界的审核反馈确认已排除")
    all_gaps = list(dict.fromkeys(gaps))
    return AgentAnalysis(
        findings=findings,
        coverage=list(coverage.values()),
        gaps=all_gaps[:4],
        addressed_issue_indices=addressed,
    ), all_gaps


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


def completion_manifest(state: ResearchGraphState) -> dict:
    """Expose machine-checked coverage and revision state to the final synthesizer."""
    reports = selected_reports(state)
    assignments = state.agent_assignments or build_assignments(state)
    coverage = {item.task_id: item for report in reports.values() for item in report.analysis.coverage}
    revisions = {
        item.role: item.status for item in state.agent_reports if item.run_id == state.turn_id and item.round == 2
    }
    tasks = [
        {
            "task_id": item.task_id,
            "role": item.role,
            "fund_code": item.fund_code,
            "status": coverage[item.task_id].status if item.task_id in coverage else "blocked",
            "explanation": coverage[item.task_id].explanation
            if item.task_id in coverage
            else (
                "个人持仓没有成功取得，组合分析未完成"
                if item.role in reports and reports[item.role].skip_reason == "no_verified_positions"
                else "角色没有有效覆盖记录"
            ),
        }
        for item in assignments
    ]
    return {
        "tasks": tasks,
        "required_count": len(tasks),
        "completed_count": sum(item["status"] == "completed" for item in tasks),
        "review_status": state.agent_review_status,
        "revision_required_roles": state.agent_revision_roles,
        "revision_status": revisions,
    }


def completion_note(state: ResearchGraphState) -> str:
    """Always publish confirmed scope and blocked tasks, even if synthesis omits them."""
    manifest = completion_manifest(state)
    roles = {"fundamentals": "产品研究", "risk": "风险与来源核验", "portfolio": "组合适配"}
    parts = ["\n\n---\n\n**研究范围核对**", "研究对象：" + "、".join(state.fund_codes)]
    for role, label in roles.items():
        tasks = [item for item in manifest["tasks"] if item["role"] == role]
        if not tasks:
            continue
        count = sum(item["status"] == "completed" for item in tasks)
        status = ""
        if role in state.agent_revision_roles and manifest["revision_status"].get(role) in {None, "failed", "skipped"}:
            status = "；修订未完成，首轮发现仍待复核"
        parts.append(label + "：已覆盖 " + str(count) + "/" + str(len(tasks)) + " 项" + status)
        for item in tasks:
            if item["status"] != "completed":
                parts.append("待完成（" + (item["fund_code"] or label) + "）：" + item["explanation"])
    if state.agent_review_status != "completed":
        parts.append("交叉审核：" + ("未完成" if state.agent_review_status == "failed" else "存在待核验项"))
    for gap in state.gaps:
        if "数据范围或质量不完整" in gap or "数据并非最新" in gap:
            for tool, label in {
                "get_fund_analysis_data": "净值历史",
                "get_fund_comparison_data": "共同窗口数据",
                "get_fund_snapshot": "基金概况",
                "get_fund_holdings": "披露持仓",
                "get_fund_managers": "经理资料",
                "get_market_events": "市场事件",
                "get_market_context": "市场概况",
                "get_fund_announcements": "基金公告",
            }.items():
                gap = gap.replace(tool, label)
            parts.append(gap)
    return "\n\n".join(parts)
