"""Research agents communicate through validated envelopes and a single review barrier."""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.agent.prompts.graph import review_prompt, role_prompt
from app.core.config import settings
from app.core.logging import logger
from app.agent.graph.evidence_matrix import build_acquisition, is_empty, retry_calls
from app.agent.graph.numeric_audit import audit_findings
from app.agent.graph.research_contract import (
    EMPTY_IS_AVAILABLE,
    ROLE_LABELS,
    build_assignments,
    completion_manifest,
    derive_coverage,
    role_evidence,
    selected_reports,
)
from app.schemas.multi_role_research import (
    AgentAnalysis,
    AgentReport,
    AgentReports,
    ResearchActivity,
    ResearchAssignment,
    ResearchProgress,
    ResearchReview,
    ResearchRole,
    ResearchStage,
)
from app.schemas.research import EvidenceAcquisition, ResearchEvidence, ResearchGraphState
from app.utils.clock import utc_now


class AgentCall(Protocol):
    """一次结构化角色调用的协议.

    ``on_text`` 是可选的一行进度观察器，只用于把思考尾部透出给界面，不影响返回值。
    """

    async def __call__(
        self,
        prompt: str,
        data: str,
        schema: type[BaseModel],
        config: RunnableConfig,
        on_text: Callable[[str], None] | None = None,
    ) -> BaseModel:
        """执行一次调用并返回校验前的结构化结果."""
        ...


EvidenceView = Callable[[ResearchGraphState], tuple[list[dict], list[str]]]
FetchEvidence = Callable[[ResearchGraphState, RunnableConfig, str, dict], Awaitable[ResearchEvidence]]
_ROLES: tuple[ResearchRole, ...] = ("performance", "risk", "holdings", "manager", "disclosure", "portfolio")


def _target_key(name: str, args: dict) -> tuple[str, tuple[str, ...]]:
    """同一工具、同一组对象视为同一取证目标，避免不同 limit 触发重复调用."""
    single = args.get("fund_code")
    if isinstance(single, str):
        return name, (single,)
    multiple = args.get("fund_codes")
    if isinstance(multiple, list):
        return name, tuple(code for code in multiple if isinstance(code, str))
    return name, ()


def _drop_resolved_failures(gaps: list[str], acquisition: list[EvidenceAcquisition]) -> list[str]:
    """补取已成功时，不再把上一轮的临时失败当成最终缺口."""
    failed_tools = {row.tool for row in acquisition if row.status == "failed"}
    resolved_tools = {row.tool for row in acquisition if row.status in {"ok", "empty"}} - failed_tools
    failure_lines = {tool + "查询失败" for tool in resolved_tools} | {tool + "补证失败" for tool in resolved_tools}
    return [gap for gap in gaps if gap not in failure_lines]


def _challenge_evidence(packet: list[dict], evidence_ids: list[str]) -> list[dict]:
    """质询证据只给有界摘录和日期，避免把整包原文再塞进修订轮."""
    by_id = {str(item.get("evidence_id")): item for item in packet}
    notes: list[dict] = []
    for evidence_id in evidence_ids:
        entry = by_id.get(evidence_id)
        if entry is None:
            continue
        text = str(entry.get("text") or "")
        date = re.search(r"\bas_of=([^\s;]+)", text)
        notes.append(
            {
                "evidence_id": evidence_id,
                "tool": entry.get("tool"),
                "args": entry.get("args") or {},
                "excerpt": text[:_REVIEW_EXCERPT_CHARS],
                "as_of": date.group(1) if date else None,
            }
        )
    return notes


def _valid_challenge(issue: Any, reports: dict[str, AgentReport], packet: list[dict]) -> bool:
    """挑战方、被挑战发现和挑战证据都必须真实且在同一角色切片内."""
    if issue.challenger_role is None or issue.challenger_role == issue.role:
        return False
    if issue.challenger_finding_index is None or not issue.challenger_evidence_ids:
        return False
    challenger = reports.get(issue.challenger_role)
    if challenger is None or issue.challenger_finding_index >= len(challenger.analysis.findings):
        return False
    finding = challenger.analysis.findings[issue.challenger_finding_index]
    visible = {item["evidence_id"] for item in role_evidence(packet, issue.challenger_role)}
    return set(issue.challenger_evidence_ids) <= set(finding.evidence_ids) <= visible


def _cross_examination_payload(
    state: ResearchGraphState, reports: dict[str, AgentReport], role: ResearchRole, packet: list[dict]
) -> list[dict]:
    """把审核已校验的挑战转成被质询角色可读的一轮修订载荷."""
    review = state.agent_review
    if review is None:
        return []
    result: list[dict] = []
    for index, issue in enumerate(review.issues):
        if issue.role != role or issue.challenger_role is None:
            continue
        challenged = reports.get(role)
        challenger = reports.get(issue.challenger_role)
        if challenged is None or challenger is None or issue.challenger_finding_index is None:
            continue
        if issue.finding_index >= len(challenged.analysis.findings):
            continue
        if issue.challenger_finding_index >= len(challenger.analysis.findings):
            continue
        challenger_finding = challenger.analysis.findings[issue.challenger_finding_index]
        result.append(
            {
                "issue_index": index,
                "challenger_role": issue.challenger_role,
                "challenger_label": ROLE_LABELS.get(issue.challenger_role, issue.challenger_role),
                "reason": issue.reason,
                "challenged_claim": challenged.analysis.findings[issue.finding_index].claim,
                "challenger_claim": challenger_finding.claim,
                "challenger_evidence": _challenge_evidence(packet, issue.challenger_evidence_ids),
            }
        )
    return result


class MultiRoleGraphState(ResearchGraphState):
    """Only agent_reports has concurrent writers; every other channel has one writer."""

    agent_reports: AgentReports = Field(default_factory=list)


class MultiRoleGraphOutput(BaseModel):
    """Return communication results without re-emitting the input conversation."""

    evidence: list[ResearchEvidence]
    gaps: list[str]
    agent_reports: list[AgentReport]
    agent_review: ResearchReview | None
    agent_assignments: list[ResearchAssignment]
    agent_evidence_packet: list[dict]
    agent_initial_evidence_ids: list[str]
    agent_revision_roles: list[ResearchRole]
    agent_review_status: Literal["completed", "partial", "failed"] | None
    agent_started_at: datetime | None
    agent_acquisition: list[EvidenceAcquisition]


def evidence_packet(state: ResearchGraphState, view: EvidenceView) -> tuple[list[dict], list[str]]:
    """Assign task-scoped IDs to the exact bounded evidence visible to agents."""
    entries, omitted = view(state)
    packet: list[dict] = []
    for entry in entries:
        if not entry.get("success"):
            continue
        digest = hashlib.sha256(
            (state.turn_id + json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)).encode()
        ).hexdigest()[:20]
        packet.append({"evidence_id": "ev_" + digest, **entry})
    return packet, omitted


def publish_progress(
    state: ResearchGraphState, stage: ResearchStage, status: Any, role: ResearchRole | None = None
) -> None:
    """Emit public progress into the custom stream; internal findings stay in checkpoints."""
    event = ResearchProgress(run_id=state.turn_id, stage=stage, role=role, status=status)
    get_stream_writer()(event.model_dump(mode="json"))


_ACTIVITY_INTERVAL_SECONDS = 0.4
_ACTIVITY_TAIL_CHARS = 80
# 审核拿到的每条被引用证据只带这么长的原文摘录：够判断支持关系，不至于重喂整包。
_REVIEW_EXCERPT_CHARS = 240


def activity_streamer(
    state: ResearchGraphState, stage: ResearchStage, role: ResearchRole | None
) -> Callable[[str], None]:
    """把角色调用的思考尾部转成一行滚动摘要：限速、截尾、单行，且不影响这次调用.

    界面只给一行空间，所以发的是"最新一段尾部"而不是全文；正文与结构化结果仍走
    各自的通道，观察器抛错一律吞掉——它坏了最多是那一行不动，不能连研究一起拖死。
    """
    tail = ""
    last = 0.0

    def emit(fragment: str) -> None:
        nonlocal tail, last
        tail = (tail + fragment)[-_ACTIVITY_TAIL_CHARS:]
        now = time.monotonic()
        if now - last < _ACTIVITY_INTERVAL_SECONDS:
            return
        last = now
        text = " ".join(tail.split())
        try:
            # 取 writer 也放在兜底里：非流式调用（例如检查点续跑走 ainvoke）时它可能不可用，
            # 那一行不动就够了，不能把研究本身弄失败。
            get_stream_writer()(
                ResearchActivity(run_id=state.turn_id, stage=stage, role=role, text=text).model_dump(mode="json")
            )
        except Exception:
            logger.debug("research_activity_dropped", turn_id=state.turn_id, stage=stage, role=role)

    return emit


def latest_reports(state: ResearchGraphState, round_number: int) -> list[AgentReport]:
    """Select envelopes belonging to this run and communication round."""
    return [item for item in state.agent_reports if item.run_id == state.turn_id and item.round == round_number]


def remaining_budget(state: ResearchGraphState) -> float:
    """A persisted start time bounds retries, supplement and revisions across resume."""
    elapsed = (utc_now() - state.agent_started_at).total_seconds() if state.agent_started_at else 0
    return max(0, settings.MULTI_ROLE_RESEARCH_TOTAL_TIMEOUT - max(0, elapsed))


def build_multi_role_subgraph(call: AgentCall, view: EvidenceView, fetch: FetchEvidence) -> CompiledStateGraph:
    """Independent analysis -> joined review -> bounded supplement -> feedback revisions."""

    async def prepare(state: MultiRoleGraphState, config: RunnableConfig) -> dict:
        packet, omitted = evidence_packet(state, view)
        assignments = build_assignments(state)
        acquisition = build_acquisition(state)
        logger.info(
            "research_evidence_acquisition",
            turn_id=state.turn_id,
            planned=len(acquisition),
            ok=sum(item.status == "ok" for item in acquisition),
            empty=sum(item.status == "empty" for item in acquisition),
            failed=sum(item.status == "failed" for item in acquisition),
            not_attempted=sum(item.status == "not_attempted" for item in acquisition),
        )
        logger.debug(
            "research_evidence_acquisition_detail",
            turn_id=state.turn_id,
            rows=[item.model_dump(mode="json") for item in acquisition],
        )
        return {
            "agent_assignments": assignments,
            "agent_evidence_packet": packet,
            "agent_initial_evidence_ids": [item["evidence_id"] for item in packet],
            "agent_acquisition": acquisition,
            "agent_revision_roles": [],
            "agent_review_status": None,
            "agent_started_at": utc_now(),
            "gaps": list(dict.fromkeys([*state.gaps, *omitted])),
        }

    def packet_for(state: ResearchGraphState, role: ResearchRole | None = None) -> list[dict]:
        packet = state.agent_evidence_packet or evidence_packet(state, view)[0]
        return role_evidence(packet, role) if role else packet

    def payload(state: ResearchGraphState, *, feedback: bool, role: ResearchRole | None = None) -> str:
        packet = packet_for(state, role)
        task = state.research_task
        if task is None or task.turn_id != state.turn_id:
            raise ValueError("research communication scope mismatch")
        data: dict[str, Any] = {
            "task": task.model_dump(mode="json"),
            "fund_codes": state.fund_codes,
            "evidence": packet,
            "scenario": state.scenario,
            "gaps": state.gaps,
            "assignments": [
                item.model_dump(mode="json")
                for item in (state.agent_assignments or build_assignments(state))
                if role is None or item.role == role
            ],
            "skill_boundaries": state.skill_evidence,
        }
        if feedback:
            first_round = latest_reports(state, 1)
            data["peer_reports"] = [item.model_dump(mode="json") for item in first_round]
            data["review"] = state.agent_review.model_dump(mode="json") if state.agent_review else None
            data["required_issue_indices"] = [
                index
                for index, issue in enumerate(state.agent_review.issues if state.agent_review else [])
                if issue.role == role
            ]
            if role is not None:
                challenges = _cross_examination_payload(
                    state, {item.role: item for item in first_round}, role, packet_for(state)
                )
                if challenges:
                    data["cross_examination"] = challenges
        if role == "portfolio" and state.long_term_memory:
            data["historical_user_statements"] = state.long_term_memory[:2000]
            data["historical_context_notice"] = (
                "历史记忆是未确认的用户表述，可能被截断；不覆盖本轮范围或已确认画像，不是资产证据。"
            )
        return json.dumps(data, ensure_ascii=False, default=str)

    async def analyze(
        state: MultiRoleGraphState, config: RunnableConfig, role: ResearchRole, round_number: Literal[1, 2]
    ) -> dict:
        stage: ResearchStage = "analysis" if round_number == 1 else "revision"
        assignment = next(
            (item for item in (state.agent_assignments or build_assignments(state)) if item.role == role), None
        )
        personal = any(item.tool == "get_positions" and item.success for item in state.evidence)
        previous = next((item for item in latest_reports(state, 1) if item.role == role), None)
        skip_reason: (
            Literal["not_applicable", "no_verified_positions", "not_required", "previous_failed", "budget"] | None
        ) = None
        if assignment is None:
            skip_reason = "not_applicable"
        elif role == "portfolio" and not personal:
            skip_reason = "no_verified_positions"
        elif round_number == 2 and previous is not None and previous.status in {"failed", "skipped"}:
            skip_reason = "previous_failed"
        elif round_number == 2 and role not in state.agent_revision_roles:
            skip_reason = "not_required"
        elif remaining_budget(state) <= 0:
            skip_reason = "budget"
        if skip_reason:
            report = AgentReport(
                run_id=state.turn_id,
                role=role,
                round=round_number,
                status="skipped",
                skip_reason=skip_reason,
            )
            publish_progress(state, stage, "skipped", role)
            return {"agent_reports": [report]}
        publish_progress(state, stage, "started", role)
        started = time.monotonic()
        input_chars = 0
        gaps: list[str] = []  # 失败路径也要能记日志：未进 try 成功分支时它得是个空清单而不是未绑定
        try:
            if assignment is None:
                # 上面已经按 not_applicable 跳过；走到这里说明跳过判定和任务清单不一致。
                raise ValueError("research assignment missing for role")
            data = payload(state, feedback=round_number == 2, role=role)
            input_chars = len(data)
            packet = packet_for(state, role)
            if not packet:
                raise ValueError("no verified research evidence")
            prompt = role_prompt(role, round_number == 2)
            async with asyncio.timeout(min(settings.MULTI_ROLE_RESEARCH_CALL_TIMEOUT, remaining_budget(state))):
                result = await call(prompt, data, AgentAnalysis, config, on_text=activity_streamer(state, stage, role))
            indices = [
                index
                for index, issue in enumerate(state.agent_review.issues if state.agent_review else [])
                if round_number == 2 and issue.role == role
            ]
            analysis, coverage, gaps = derive_coverage(
                AgentAnalysis.model_validate(result),
                packet,
                assignment,
                list(state.fund_codes),
                indices,
                state.agent_acquisition,
            )
            task = state.research_task
            if (
                role == "portfolio"
                and task is not None
                and task.request.intent == "allocation_analysis"
                and not state.scenario.get("available")
            ):
                note = "代码配置情景不可用，只给条件方案"
                gaps = [*gaps, note]
                analysis = analysis.model_copy(update={"gaps": list(dict.fromkeys([*analysis.gaps, note]))[:4]})
            status = (
                "failed"
                if not analysis.findings
                else "completed"
                if coverage.status == "completed" and not gaps
                else "partial"
            )
            try:
                numeric = audit_findings(analysis.findings, packet, state.evidence)
                logger.info(
                    "research_numeric_audit",
                    turn_id=state.turn_id,
                    role=role,
                    checked=numeric.checked,
                    matched=numeric.matched,
                    unmatched=len(numeric.unmatched),
                    truncated=numeric.truncated,
                )
            except Exception:
                logger.exception("research_numeric_audit_failed", turn_id=state.turn_id, role=role)
                numeric = None
            report = AgentReport(
                run_id=state.turn_id,
                role=role,
                round=round_number,
                status=status,
                analysis=analysis,
                coverage=coverage,
                numeric_audit=numeric,
            )
        except Exception:
            logger.exception("research_agent_failed", turn_id=state.turn_id, role=role, round=round_number)
            report = AgentReport(
                run_id=state.turn_id,
                role=role,
                round=round_number,
                status="failed",
                analysis=AgentAnalysis(gaps=["该角色未完成有效分析，不能视为同意其他角色"]),
            )
        publish_progress(state, stage, report.status, role)
        logger.info(
            "research_agent_completed",
            turn_id=state.turn_id,
            role=role,
            round=round_number,
            status=report.status,
            finding_count=len(report.analysis.findings),
            gap_count=len(report.analysis.gaps),
            elapsed_seconds=round(time.monotonic() - started, 3),
            input_chars=input_chars,
            coverage_status=report.coverage.status if report.coverage is not None else None,
            met_count=len(report.coverage.met) if report.coverage is not None else 0,
            missing_count=len(report.coverage.missing) if report.coverage is not None else 0,
            # 覆盖 completed 却仍然 partial 时，只有这两项能说明原因（伪引用条数 + 服务端缺陷清单）。
            dropped_citations=report.coverage.dropped_citations if report.coverage is not None else 0,
            hard_gaps=gaps,
        )
        return {"agent_reports": [report]}

    def review_payload(state: MultiRoleGraphState) -> str:
        """审核读结论 + 被真正引用到的那几条证据摘录，不再重读整包原文.

        这条是整链里最慢最贵的一次调用（实测 47-90 秒、~21k 字符输入，两次正好撞在
        90 秒超时上）。它要判断的是「这条结论有没有被它引用的证据支持」，所以留有界
        摘录就够了；把整包原始数据再喂一遍只是把成本搬到最没有产出的一环。
        """
        packet = packet_for(state)
        cited = {
            evidence_id
            for report in latest_reports(state, 1)
            for finding in report.analysis.findings
            for evidence_id in finding.evidence_ids
        }
        index = {
            item["evidence_id"]: {
                "tool": item["tool"],
                "args": item.get("args") or {},
                "excerpt": (item.get("text") or "")[:_REVIEW_EXCERPT_CHARS],
            }
            for item in packet
            if item["evidence_id"] in cited
        }
        task = state.research_task
        return json.dumps(
            {
                "task": task.model_dump(mode="json") if task is not None else None,
                "fund_codes": state.fund_codes,
                "assignments": [
                    item.model_dump(mode="json") for item in (state.agent_assignments or build_assignments(state))
                ],
                "peer_reports": [
                    {
                        "role": item.role,
                        "status": item.status,
                        "findings": [finding.model_dump(mode="json") for finding in item.analysis.findings],
                        "gaps": item.analysis.gaps,
                        "stance": item.analysis.stance.model_dump(mode="json") if item.analysis.stance else None,
                        "coverage": item.coverage.model_dump(mode="json") if item.coverage else None,
                        "numeric_audit": item.numeric_audit.model_dump(mode="json") if item.numeric_audit else None,
                    }
                    for item in latest_reports(state, 1)
                ],
                "cited_evidence": index,
                "gaps": state.gaps,
            },
            ensure_ascii=False,
            default=str,
        )

    async def review(state: MultiRoleGraphState, config: RunnableConfig) -> dict:
        publish_progress(state, "review", "started")
        started = time.monotonic()
        data = review_payload(state)
        packet = packet_for(state)
        ids = {item["evidence_id"] for item in packet}
        reports = {item.role: item for item in latest_reports(state, 1)}
        if set(reports) != set(_ROLES):
            raise ValueError("research review barrier missing agent reports")
        try:
            if not any(item.analysis.findings for item in reports.values()):
                raise ValueError("no verified role findings")
            if remaining_budget(state) <= 0:
                raise TimeoutError("research review budget exhausted")
            async with asyncio.timeout(min(settings.MULTI_ROLE_RESEARCH_CALL_TIMEOUT, remaining_budget(state))):
                result = await call(
                    review_prompt(),
                    data,
                    ResearchReview,
                    config,
                    on_text=activity_streamer(state, "review", None),
                )
            checked = ResearchReview.model_validate(result)
            base_issues = [
                issue
                for issue in checked.issues
                if issue.finding_index < len(reports[issue.role].analysis.findings)
                and set(issue.evidence_ids).issubset(ids)
            ]
            valid_supplements = [
                item
                for item in checked.supplements
                if (item.kind == "market_events" and item.fund_code is None)
                or (item.kind != "market_events" and item.fund_code in state.fund_codes)
            ]
            invalid = len(base_issues) != len(checked.issues) or len(valid_supplements) != len(checked.supplements)
            valid_issues = []
            challenges = 0
            for issue in base_issues:
                has_challenge = (
                    issue.challenger_role is not None
                    or issue.challenger_finding_index is not None
                    or bool(issue.challenger_evidence_ids)
                )
                if not has_challenge:
                    valid_issues.append(issue)
                    continue
                if challenges < 2 and _valid_challenge(issue, reports, packet):
                    valid_issues.append(issue)
                    challenges += 1
                    continue
                logger.info(
                    "research_challenge_rejected",
                    turn_id=state.turn_id,
                    role=issue.role,
                    challenger_role=issue.challenger_role,
                )
                valid_issues.append(
                    issue.model_copy(
                        update={
                            "challenger_role": None,
                            "challenger_finding_index": None,
                            "challenger_evidence_ids": [],
                        }
                    )
                )
            gaps = [*state.gaps, *checked.gaps, *(["审核中的无效反馈或越界补证请求已排除"] if invalid else [])]
            checked = checked.model_copy(update={"issues": valid_issues, "supplements": valid_supplements})
            status = "partial" if invalid or checked.gaps else "completed"
        except Exception:
            logger.exception("research_review_failed", turn_id=state.turn_id)
            checked = ResearchReview(gaps=["交叉审核失败，结论尚未完成审核"])
            gaps = [*state.gaps, *checked.gaps]
            status = "failed"
        publish_progress(state, "review", status)
        logger.info(
            "research_review_completed",
            turn_id=state.turn_id,
            status=status,
            elapsed_seconds=round(time.monotonic() - started, 3),
            input_chars=len(data),
        )
        return {"agent_review": checked, "agent_review_status": status, "gaps": list(dict.fromkeys(gaps))}

    async def supplement(state: MultiRoleGraphState, config: RunnableConfig) -> dict:
        requests = state.agent_review.supplements if state.agent_review else []
        started = time.monotonic()
        evidence = list(state.evidence)
        gaps = list(state.gaps)
        seen = {(item.tool, json.dumps(item.args, sort_keys=True)) for item in evidence}
        calls: list[tuple[str, dict]] = []
        for request in requests:
            if request.kind == "market_events":
                name, args = "get_market_events", {"limit": 10, "lookback_hours": 168}
            elif request.kind == "announcements":
                name, args = "get_fund_announcements", {"fund_code": request.fund_code, "category": "all", "limit": 10}
            else:
                name, args = "get_fund_managers", {"fund_code": request.fund_code, "limit": 20}
            key = (name, json.dumps(args, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            calls.append((name, args))
        attempted_targets = {_target_key(name, args) for name, args in calls}
        if state.agent_review_status != "failed":
            acquisition = state.agent_acquisition or build_acquisition(state)
            for name, args in retry_calls(state, acquisition):
                target = _target_key(name, args)
                if target in attempted_targets:
                    continue
                attempted_targets.add(target)
                calls.append((name, args))
        publish_progress(state, "supplement", "started" if calls else "skipped")

        async def one(name: str, args: dict) -> ResearchEvidence:
            try:
                if remaining_budget(state) <= 0:
                    raise TimeoutError("research supplement budget exhausted")
                async with asyncio.timeout(remaining_budget(state)):
                    return await fetch(state, config, name, args)
            except Exception:
                logger.exception("research_supplement_failed", turn_id=state.turn_id, tool_name=name)
                return ResearchEvidence(tool=name, args=args, success=False, text="[TOOL_ERROR] 补证未完成")

        obtained_items = await asyncio.gather(*(one(name, args) for name, args in calls))
        for obtained in obtained_items:
            evidence.append(obtained)
            if not obtained.success:
                gaps.append(obtained.tool + "补证失败")
        updated = state.model_copy(update={"evidence": evidence})
        packet, omitted = evidence_packet(updated, view)
        acquisition = build_acquisition(updated)
        gaps.extend(omitted)
        usable = {
            (item.tool, json.dumps(item.args, sort_keys=True))
            for item in evidence
            if item.success and (not is_empty(item.tool, item.data) or item.tool in EMPTY_IS_AVAILABLE)
        }
        revision_roles: set[ResearchRole] = set()
        if state.agent_review_status != "failed":
            revision_roles.update(issue.role for issue in (state.agent_review.issues if state.agent_review else []))
            for role, report in selected_reports(state).items():
                if report.status not in {"completed", "partial"}:
                    continue
                visible = role_evidence(packet, role)
                new_usable = any(
                    item["evidence_id"] not in state.agent_initial_evidence_ids
                    and (item["tool"], json.dumps(item.get("args") or {}, sort_keys=True)) in usable
                    for item in visible
                )
                if new_usable:
                    revision_roles.add(role)
                if report.coverage is not None and report.coverage.revision_needed:
                    revision_roles.add(role)
        if calls:
            publish_progress(
                state, "supplement", "partial" if any(not item.success for item in obtained_items) else "completed"
            )
        logger.info(
            "research_supplement_completed",
            turn_id=state.turn_id,
            call_count=len(calls),
            revision_roles=sorted(revision_roles),
            failed_calls=sum(not item.success for item in obtained_items),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        return {
            "evidence": evidence,
            "gaps": list(dict.fromkeys(gaps)),
            "agent_evidence_packet": packet,
            "agent_acquisition": acquisition,
            "agent_revision_roles": sorted(revision_roles),
        }

    async def complete(state: MultiRoleGraphState, config: RunnableConfig) -> dict:
        gaps = _drop_resolved_failures(list(state.gaps), state.agent_acquisition)
        manifest = completion_manifest(state)
        for item in manifest["tasks"]:
            # 未运行也是一个要披露的结局：用户要求"结合我的持仓"而持仓没取到时，
            # 报告不能装作这一维度分析过了。
            if item["status"] != "completed":
                gaps.append(ROLE_LABELS.get(item["role"], item["role"]) + "：" + item["explanation"])
        for report in selected_reports(state).values():
            # 该维度已经完全覆盖时，它自述的数据局限是脚注不是运行缺陷：照常进报告正文，
            # 但不汇进 state.gaps，否则每次深度研究都必然 partial（实测踩过）。
            if report.status in {"skipped", "completed"}:
                continue
            gaps.extend(ROLE_LABELS.get(report.role, report.role) + "：" + gap for gap in report.analysis.gaps)
        revisions = {item.role: item for item in latest_reports(state, 2)}
        for role in state.agent_revision_roles:
            if role not in revisions or revisions[role].status in {"failed", "skipped"}:
                gaps.append(ROLE_LABELS.get(role, role) + "修订未完成，保留首轮发现但审核反馈尚未解决")
        if remaining_budget(state) <= 0:
            gaps.append("多角色分析达到总时限；未完成项不能视为通过")
        logger.info(
            "research_roles_completed",
            turn_id=state.turn_id,
            completed_count=manifest["completed_count"],
            required_count=manifest["required_count"],
            elapsed_seconds=(utc_now() - state.agent_started_at).total_seconds() if state.agent_started_at else None,
        )
        return {
            "gaps": list(dict.fromkeys(gaps)),
            "agent_assignments": state.agent_assignments or build_assignments(state),
        }

    graph = StateGraph(MultiRoleGraphState, output_schema=MultiRoleGraphOutput)
    graph.add_node("prepare_agents", prepare)
    graph.add_edge(START, "prepare_agents")
    for role in _ROLES:

        async def first(state: MultiRoleGraphState, config: RunnableConfig, selected: ResearchRole = role) -> dict:
            return await analyze(state, config, selected, 1)

        async def second(state: MultiRoleGraphState, config: RunnableConfig, selected: ResearchRole = role) -> dict:
            return await analyze(state, config, selected, 2)

        graph.add_node(role + "_analysis", first, metadata={"research_internal": True})
        graph.add_node(role + "_revision", second, metadata={"research_internal": True})
        graph.add_edge("prepare_agents", role + "_analysis")
        graph.add_edge("supplement", role + "_revision")
    graph.add_node("review_agents", review, metadata={"research_internal": True})
    graph.add_node("supplement", supplement)
    graph.add_node("complete_agents", complete)
    graph.add_edge([role + "_analysis" for role in _ROLES], "review_agents")
    graph.add_edge("review_agents", "supplement")
    graph.add_edge([role + "_revision" for role in _ROLES], "complete_agents")
    graph.add_edge("complete_agents", END)
    return graph.compile(name="multi_role_research")
