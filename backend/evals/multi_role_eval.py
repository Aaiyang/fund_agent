"""离线多角色 fixture 评测：固定证据包驱动真实子图，不调用模型或网络.

指标只用于回归：覆盖率、未知引用、修订闭环、重复结论、调用次数和估算 token。
它不是投资质量评测，也不替代真实模型的线上 eval。
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import tiktoken
from pydantic import BaseModel

from app.agent.graph.multi_role_research import build_multi_role_subgraph
from app.agent.graph.research import multi_role_evidence
from app.agent.graph.research_contract import completion_manifest, divergences, selected_reports
from app.agent.tools.result import ToolResult
from app.schemas.multi_role_research import (
    AgentAnalysis,
    EvidenceFinding,
    ResearchReview,
    ReviewIssue,
)
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask

_FIXTURES = Path(__file__).parent / "fixtures" / "multi_role" / "cases.json"
_ENCODER = tiktoken.get_encoding("cl100k_base")
_ROLES = ("performance", "risk", "holdings", "manager", "disclosure", "portfolio")


def _success(tool: str, args: dict, data: dict) -> ResearchEvidence:
    return ResearchEvidence(
        tool=tool,
        args=args,
        success=True,
        text=ToolResult.ok(data).to_text(),
        data=data,
        status="ok",
    )


def _failure(tool: str, args: dict, retryable: bool = False) -> ResearchEvidence:
    return ResearchEvidence(
        tool=tool,
        args=args,
        success=False,
        text=ToolResult.fail("DATA_NOT_AVAILABLE", "fixture 不可用", retryable=retryable).to_text(),
        status="failed",
        error_code="DATA_NOT_AVAILABLE",
        retryable=retryable,
    )


def _comparison_data(codes: list[str], missing_risk: set[str]) -> dict:
    rows = []
    for index, code in enumerate(codes):
        row = {
            "fund_code": code,
            "window_change_ratio": 0.1 * (index + 1),
            "observed_max_drawdown_ratio": -0.1 * (index + 1),
            "annualized_nav_volatility_ratio": 0.2 * (index + 1),
            "sharpe_ratio_rf0": 0.5,
            "sortino_ratio_rf0": 0.7,
            "aligned_count": 240,
        }
        if code in missing_risk:
            row["observed_max_drawdown_ratio"] = None
            row["annualized_nav_volatility_ratio"] = None
            row["sharpe_ratio_rf0"] = None
            row["sortino_ratio_rf0"] = None
        rows.append(row)
    return {"status": "completed", "common_count": 240, "rows": rows}


def _benchmark_data(code: str) -> dict:
    return {
        "fund_code": code,
        "range_key": "3y",
        "benchmark_text": "沪深300指数收益率",
        "parts": [{"weight_pp": 100}],
        "aligned_days": 240,
    }


def _build_evidence(case: dict) -> list[ResearchEvidence]:
    codes = list(case["fund_codes"])
    missing_risk = set(case.get("missing_risk_metrics", []))
    empty_holdings = set(case.get("empty_holdings", []))
    failed = case.get("failed_tools", {})
    missing = case.get("missing_tools", {})
    evidence: list[ResearchEvidence] = []
    if case["intent"] == "fund_comparison":
        evidence.append(
            _success(
                "get_fund_comparison_data",
                {"fund_codes": codes},
                _comparison_data(codes, missing_risk),
            )
        )
    for code in codes:
        evidence.append(_success("get_fund_snapshot", {"fund_code": code}, {"fund_code": code, "latest_nav": 1.2}))
        if case["intent"] != "fund_comparison":
            metrics = {
                "observed_max_drawdown_ratio": None if code in missing_risk else -0.2,
                "annualized_nav_volatility_ratio": None if code in missing_risk else 0.3,
            }
            evidence.append(
                _success(
                    "get_fund_analysis_data",
                    {"fund_code": code},
                    {"fund_code": code, "raw_count": 240, "metrics": metrics},
                )
            )
        if "get_fund_holdings" not in missing.get(code, []):
            evidence.append(
                _success(
                    "get_fund_holdings",
                    {"fund_code": code},
                    {"fund_code": code, "top_holdings": [] if code in empty_holdings else [{"weight": 6.45}]},
                )
            )
        evidence.append(
            _success(
                "get_fund_managers",
                {"fund_code": code, "limit": 10},
                {
                    "fund_code": code,
                    "periods": [{"managers": [{"name": "fixture"}], "start_date": "2021-01-01", "is_current": True}],
                },
            )
        )
        evidence.append(
            _success(
                "get_fund_announcements",
                {"fund_code": code, "category": "all", "limit": 5},
                {"fund_code": code, "items": [{"title": "fixture 公告"}]},
            )
        )
        benchmark_failed = "get_fund_benchmark" in failed.get(code, [])
        benchmark_args = {"fund_code": code, "range_key": "3y"}
        evidence.append(
            _failure("get_fund_benchmark", benchmark_args, retryable=True)
            if benchmark_failed
            else _success("get_fund_benchmark", benchmark_args, _benchmark_data(code))
        )
    return evidence


def _matches(entry: dict, tools: list[str], code: str | None) -> bool:
    if entry["tool"] not in tools:
        return False
    args = entry.get("args") or {}
    return code is None or args.get("fund_code") == code or code in (args.get("fund_codes") or [])


def _analysis_for(payload: dict, role: str, case: dict, feedback: bool) -> AgentAnalysis:
    assignment = payload["assignments"][0]
    evidence = payload["evidence"]
    uncited = {item["tool"] for item in case.get("uncited", []) if item.get("role") == role and not feedback}
    findings: list[EvidenceFinding] = []
    for requirement in assignment["required_evidence"]:
        if any(tool in uncited for tool in requirement["tools"]):
            continue
        codes = payload["fund_codes"] if requirement["scope"] == "per_fund" else [None]
        refs = [
            entry["evidence_id"] for code in codes for entry in evidence if _matches(entry, requirement["tools"], code)
        ]
        refs = list(dict.fromkeys(refs))[:6]
        if not refs:
            continue
        claim = "共享模拟结论" if case.get("duplicate_claims") else f"{role}:{requirement['label']}"
        findings.append(EvidenceFinding(claim=claim, kind="inference", evidence_ids=refs, limitation="fixture"))
    if role in case.get("forged_roles", []) and not feedback:
        findings = [EvidenceFinding(claim="伪造引用", kind="fact", evidence_ids=["ev_forged"], limitation="fixture")]
    return AgentAnalysis(
        findings=findings[:6],
        addressed_issue_indices=payload.get("required_issue_indices", []) if feedback else [],
    )


def _review_for(payload: dict, case: dict) -> ResearchReview:
    spec = case.get("review_issue")
    if not spec:
        return ResearchReview()
    peers = {item["role"]: item for item in payload["peer_reports"]}
    target = peers.get(spec["role"])
    if target is None or not target["findings"]:
        return ResearchReview()
    issue = ReviewIssue(
        role=spec["role"],
        finding_index=spec["finding_index"],
        reason="fixture 质询",
        evidence_ids=target["findings"][spec["finding_index"]]["evidence_ids"][:6],
    )
    challenger = spec.get("challenger")
    if challenger:
        source = peers.get(challenger)
        if source is not None and source["findings"]:
            issue = issue.model_copy(
                update={
                    "challenger_role": challenger,
                    "challenger_finding_index": 0,
                    "challenger_evidence_ids": source["findings"][0]["evidence_ids"][:3],
                }
            )
    return ResearchReview(issues=[issue])


def _normalize_claim(claim: str) -> str:
    return re.sub(r"\s+", "", claim).casefold()


async def run_case(case: dict) -> dict:
    """驱动一次真实多角色子图；模型、工具和审查都是确定性 fixture."""
    task = ResearchTask(
        turn_id=case["id"],
        request=ResearchRequest(
            intent=case["intent"],
            mode="deep",
            strategy="multi_role",
            fund_queries=list(case["fund_codes"]),
        ),
        instruction="fixture evaluation",
    )
    evidence = _build_evidence(case)
    state = ResearchGraphState(
        turn_id=task.turn_id, research_task=task, fund_codes=list(case["fund_codes"]), evidence=evidence
    )
    metrics = {"calls": 0, "fetch_calls": 0, "input_chars": 0, "input_tokens": 0, "output_tokens": 0}

    async def call(prompt: str, data: str, schema: type[BaseModel], config: Any, on_text: Any = None) -> BaseModel:
        del prompt, config, on_text
        metrics["calls"] += 1
        metrics["input_chars"] += len(data)
        metrics["input_tokens"] += len(_ENCODER.encode(data))
        payload = json.loads(data)
        if schema is ResearchReview:
            return _review_for(payload, case)
        role = payload["assignments"][0]["role"]
        feedback = "peer_reports" in payload
        if role in case.get("role_failures", []) and not feedback:
            metrics["output_tokens"] += 1
            raise RuntimeError("fixture role failure")
        analysis = _analysis_for(payload, role, case, feedback)
        metrics["output_tokens"] += len(
            _ENCODER.encode(json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False))
        )
        return analysis

    async def fetch(state: ResearchGraphState, config: Any, name: str, args: dict) -> ResearchEvidence:
        del state, config
        metrics["fetch_calls"] += 1
        if name == "get_fund_benchmark" and case.get("retry_benchmark_success"):
            return _success(name, args, _benchmark_data(args["fund_code"]))
        return _failure(name, args)

    graph = build_multi_role_subgraph(call, multi_role_evidence, fetch)
    started = time.monotonic()
    output = await graph.ainvoke(state)
    wall_ms = (time.monotonic() - started) * 1000
    result_state = state.model_copy(update=output)
    manifest = completion_manifest(result_state)
    coverage = {task["role"]: task["status"] for task in manifest["tasks"]}
    reports = result_state.agent_reports
    first = [item for item in reports if item.run_id == task.turn_id and item.round == 1]
    unknown = sum(item.coverage.dropped_citations for item in first if item.coverage is not None)
    selected = selected_reports(result_state)
    claims = [finding.claim for report in selected.values() for finding in report.analysis.findings]
    normalized = [_normalize_claim(claim) for claim in claims]
    divergence_rows = divergences(result_state)
    challenge_count = sum(
        1 for issue in (result_state.agent_review.issues if result_state.agent_review else []) if issue.challenger_role
    )
    return {
        "id": case["id"],
        "coverage": coverage,
        "revision_roles": sorted(output.get("agent_revision_roles", [])),
        "unknown_citations": unknown,
        "findings": len(claims),
        "duplicate_claims": len(normalized) - len(set(normalized)),
        "challenge_count": challenge_count,
        "divergences": len(divergence_rows),
        "resolved_divergences": sum(bool(item["resolved"]) for item in divergence_rows),
        "calls": metrics["calls"],
        "fetch_calls": metrics["fetch_calls"],
        "input_chars": metrics["input_chars"],
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "wall_ms": round(wall_ms, 3),
    }


async def evaluate(cases_path: Path = _FIXTURES) -> dict:
    """运行全部固定 case，返回逐 case 指标与汇总."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = [await run_case(case) for case in cases]
    total_findings = sum(item["findings"] for item in results)
    unknown = sum(item["unknown_citations"] for item in results)
    return {
        "version": 1,
        "case_count": len(cases),
        "results": results,
        "summary": {
            "unknown_citation_rate": unknown / total_findings if total_findings else 0.0,
            "total_unknown_citations": unknown,
            "total_findings": total_findings,
            "mean_calls": round(sum(item["calls"] for item in results) / len(results), 2),
            "mean_input_tokens": round(sum(item["input_tokens"] for item in results) / len(results), 1),
            "max_wall_ms": max(item["wall_ms"] for item in results),
        },
    }
