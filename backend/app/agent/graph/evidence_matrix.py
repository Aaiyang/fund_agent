"""按研究意图和对象生成确定性取证计划；计划、角色补取与补证共用同一套参数."""

import json
import re
from dataclasses import dataclass
from typing import Literal

from app.agent.graph.research_contract import build_assignments
from app.schemas.multi_role_research import ResearchRole
from app.schemas.research import EvidenceAcquisition, EvidenceStatus, ResearchEvidence, ResearchGraphState

RoleScope = Literal["per_fund", "global"]
AcquisitionStage = Literal["plan", "role", "supplement"]

ROLE_TOOL_ARGS: dict[str, dict] = {
    "get_fund_managers": {"limit": 10},
    "get_fund_announcements": {"category": "all", "limit": 5},
    "get_fund_benchmark": {"range_key": "3y"},
    "get_fund_sectors": {"limit": 2},
    "get_market_events": {"limit": 5, "lookback_hours": 72},
    "get_sector_market": {"limit": 3},
}
CODE_FREE_TOOLS = frozenset({"get_portfolio", "get_positions", "get_market_context", "get_market_events"})
PER_FUND_TOOLS = frozenset(
    {
        "get_fund_snapshot",
        "get_fund_analysis_data",
        "get_fund_holdings",
        "get_fund_managers",
        "get_fund_announcements",
        "get_fund_benchmark",
        "get_fund_sectors",
    }
)
ROLE_EVIDENCE_CAP = 4
MAX_ATTEMPTS = 2
MAX_RETRIES = 3
RETRYABLE_ERRORS = frozenset({"RESEARCH_DATA_UNAVAILABLE", "UPSTREAM_ERROR", "TIMEOUT", "NETWORK_ERROR", "EMPTY"})
NON_RETRYABLE_ERRORS = frozenset({"DATA_NOT_AVAILABLE", "FUND_NOT_FOUND", "INVALID_ARGUMENT", "INVALID_SYMBOL"})
PRIVATE_TOOLS = frozenset({"get_positions", "get_portfolio", "get_portfolio_snapshot", "get_watchlist"})
_RISK_METRICS = ("observed_max_drawdown_ratio", "annualized_nav_volatility_ratio")


@dataclass(frozen=True)
class MatrixCall:
    """一条由代码生成、可直接执行或核对的取证调用."""

    name: str
    args: dict
    scope: RoleScope
    fund_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleCall:
    """一条角色必需证据；角色补取和覆盖分类都从它派生."""

    role: ResearchRole
    requirement: str
    name: str
    args: dict
    scope: RoleScope
    fund_code: str | None = None


def _market_needed(state: ResearchGraphState, intent: str) -> bool:
    """复刻现有 plan 的市场上下文判断，保持所有意图的调用顺序不变."""
    task = state.research_task
    if task is None:
        return False
    if intent == "stock_research":
        return task.request.mode == "deep" or bool(re.search(r"原因|为什么|政策|利好|利空", task.instruction))
    if intent == "sector_research":
        return True
    return (
        task.request.mode == "deep"
        or intent == "allocation_analysis"
        or bool(re.search(r"涨跌|为什么.*(?:涨|跌)|原因|政策|利好|利空", task.instruction))
    )


def _matrix_call(name: str, args: dict) -> MatrixCall:
    codes = ()
    if isinstance(args.get("fund_code"), str):
        codes = (args["fund_code"],)
    elif isinstance(args.get("fund_codes"), list):
        codes = tuple(code for code in args["fund_codes"] if isinstance(code, str))
    return MatrixCall(name=name, args=args, scope="per_fund" if codes else "global", fund_codes=codes)


def plan_calls(state: ResearchGraphState) -> list[MatrixCall]:
    """按 intent × mode × fund 生成基础取证计划；顺序与历史计划逐项一致."""
    task = state.research_task
    if task is None:
        raise ValueError("research task missing")
    request = task.request
    intent = request.intent
    calls: list[tuple[str, dict]] = []
    market_needed = _market_needed(state, intent)
    if intent == "stock_research":
        calls.append(("get_stock_analysis_data", {"symbol": request.stock_symbol}))
    elif intent == "sector_research":
        calls.append(("get_sector_market", {"keyword": request.sector_query, "limit": 3}))
    if intent == "fund_comparison":
        calls.append(("get_fund_comparison_data", {"fund_codes": state.fund_codes}))
    for code in state.fund_codes:
        names = (
            ("get_fund_snapshot", "get_fund_holdings")
            if intent == "fund_comparison"
            else ("get_fund_snapshot", "get_fund_analysis_data", "get_fund_holdings")
        )
        calls.extend((name, {"fund_code": code}) for name in names)
        if intent != "portfolio_diagnosis" or request.mode == "deep":
            calls.append(("get_fund_managers", {"fund_code": code, "limit": 10}))
        if request.mode == "deep":
            calls.append(("get_fund_announcements", {"fund_code": code, "category": "all", "limit": 5}))
            calls.append(("get_fund_benchmark", {"fund_code": code, "range_key": "3y"}))
        if market_needed:
            calls.append(("get_fund_sectors", {"fund_code": code, "limit": 2}))
    if market_needed:
        if intent != "stock_research" or str(request.stock_symbol).startswith(("sh", "sz", "bj")):
            calls.append(("get_market_context", {}))
        calls.append(("get_market_events", {"limit": 5, "lookback_hours": 72}))
    return [_matrix_call(name, args) for name, args in calls]


def tool_args(name: str, code: str | None, state: ResearchGraphState) -> dict | None:
    """按工具名给出与基础计划一致的入参；未知工具返回 None，不猜参数."""
    extra = ROLE_TOOL_ARGS.get(name, {})
    if name in CODE_FREE_TOOLS:
        return dict(extra)
    if name == "get_fund_comparison_data":
        return {"fund_codes": list(state.fund_codes)} if len(state.fund_codes) > 1 else None
    if name == "get_sector_market":
        task = state.research_task
        keyword = task.request.sector_query if task is not None else None
        return {"keyword": keyword, **extra} if keyword else None
    if name in PER_FUND_TOOLS:
        return {"fund_code": code, **extra} if code else None
    return None


def _args_key(args: dict) -> str:
    """与采集节点一致的可比较入参指纹."""
    return json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)


def _codes_from_args(args: dict) -> list[str]:
    single = args.get("fund_code")
    if isinstance(single, str):
        return [single]
    multiple = args.get("fund_codes")
    if isinstance(multiple, list):
        return [code for code in multiple if isinstance(code, str)]
    return []


def is_empty(tool: str, data: object) -> bool:
    """工具成功返回但没有业务数据；空公告/空事件是有效结果，由 EMPTY_IS_AVAILABLE 另判."""
    if data is None:
        return True
    if not isinstance(data, dict):
        return not bool(data)
    if tool == "get_fund_comparison_data":
        return data.get("status") == "unavailable" or not data.get("rows")
    if tool == "get_fund_analysis_data":
        return data.get("raw_count", 0) == 0 and not data.get("metrics")
    if tool == "get_fund_holdings":
        return not data.get("top_holdings")
    if tool == "get_fund_managers":
        return not data.get("periods") and not data.get("tenures")
    if tool == "get_fund_announcements":
        return not data.get("items")
    if tool == "get_fund_benchmark":
        return not data.get("benchmark_text") and not data.get("parts")
    if tool in {"get_fund_sectors", "get_sector_market"}:
        return not data.get("sectors")
    if tool == "get_market_events":
        return not data.get("events")
    if tool == "get_positions":
        return not data.get("positions")
    if tool == "get_portfolio":
        return not data.get("positions") and not data.get("summary")
    return not data


def missing_metrics(tool: str, data: object) -> tuple[list[str], list[str]]:
    """返回（缺失指标名，缺失基金代码）；这是覆盖分类的机器依据."""
    if not isinstance(data, dict):
        return [], []
    if tool == "get_fund_comparison_data":
        rows = data.get("rows")
        if not isinstance(rows, list):
            return [], []
        missing_codes: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = row.get("fund_code")
            if isinstance(code, str) and (
                row.get("observed_max_drawdown_ratio") is None or row.get("annualized_nav_volatility_ratio") is None
            ):
                missing_codes.append(code)
        return (list(_RISK_METRICS) if missing_codes else []), missing_codes
    if tool == "get_fund_analysis_data":
        metrics = data.get("metrics")
        if not isinstance(metrics, dict):
            return ["风险指标"], ([data["fund_code"]] if isinstance(data.get("fund_code"), str) else [])
        missing = [name for name in _RISK_METRICS if metrics.get(name) is None]
        code = data.get("fund_code")
        return missing, ([code] if missing and isinstance(code, str) else [])
    if tool == "get_fund_benchmark" and data.get("unavailable_reason"):
        code = data.get("fund_code")
        return ["相对基准指标"], ([code] if isinstance(code, str) else [])
    return [], []


def _evidence_status(item: ResearchEvidence) -> EvidenceStatus:
    if item.status in {"ok", "empty", "failed"}:
        return item.status
    if not item.success:
        return "failed"
    return "empty" if is_empty(item.tool, item.data) else "ok"


def build_acquisition(state: ResearchGraphState, *, include_required: bool = True) -> list[EvidenceAcquisition]:
    """把计划、角色补取和已有证据对齐成可核对的取得台账."""
    ordered: list[tuple[MatrixCall, AcquisitionStage]] = []
    seen: set[tuple[str, str]] = set()
    for call in plan_calls(state):
        key = (call.name, _args_key(call.args))
        if key not in seen:
            seen.add(key)
            ordered.append((call, "plan"))
    if include_required:
        for call in required_calls(state):
            key = (call.name, _args_key(call.args))
            if key not in seen:
                seen.add(key)
                ordered.append(
                    (MatrixCall(call.name, call.args, call.scope, (call.fund_code,) if call.fund_code else ()), "role")
                )
    evidence_by_key: dict[tuple[str, str], list[ResearchEvidence]] = {}
    for item in state.evidence:
        evidence_by_key.setdefault((item.tool, _args_key(item.args)), []).append(item)
    for key, items in evidence_by_key.items():
        if key in seen:
            continue
        seen.add(key)
        latest = items[-1]
        ordered.append(
            (
                MatrixCall(latest.tool, latest.args, "per_fund" if _codes_from_args(latest.args) else "global"),
                "supplement",
            )
        )

    rows: list[EvidenceAcquisition] = []
    for call, stage in ordered:
        key = (call.name, _args_key(call.args))
        items = evidence_by_key.get(key, [])
        chosen = next((item for item in reversed(items) if item.success), items[-1] if items else None)
        if chosen is None:
            rows.append(
                EvidenceAcquisition(
                    tool=call.name,
                    args=call.args,
                    fund_codes=_codes_from_args(call.args),
                    status="not_attempted",
                    stage=stage,
                    retryable=True,
                )
            )
            continue
        status = _evidence_status(chosen)
        metric_names, missing_codes = missing_metrics(call.name, chosen.data)
        retryable = status == "failed" and (
            chosen.retryable
            or (chosen.error_code in RETRYABLE_ERRORS and chosen.error_code not in NON_RETRYABLE_ERRORS)
        )
        rows.append(
            EvidenceAcquisition(
                tool=call.name,
                args=call.args,
                fund_codes=_codes_from_args(call.args),
                status=status,
                stage=stage,
                error_code=chosen.error_code,
                retryable=retryable,
                attempts=len(items),
                missing_metrics=metric_names,
                missing_fund_codes=missing_codes,
            )
        )
    return rows


def retry_calls(
    state: ResearchGraphState, acquisition: list[EvidenceAcquisition], *, limit: int = MAX_RETRIES
) -> list[tuple[str, dict]]:
    """只对角色必需、可重试且尚未成功的取证做一次有界补取."""
    required_keys = {(call.name, _args_key(call.args)) for call in required_calls(state)}
    successful_keys = {(item.tool, _args_key(item.args)) for item in state.evidence if item.success}
    candidates: list[tuple[str, dict]] = []
    seen: set[tuple[str, str]] = set()
    # 失败项优先：未尝试项可能很多，不能把真正失败的工具挤出有界补取名额。
    ordered = sorted(acquisition, key=lambda row: 0 if row.status == "failed" else 1)
    for row in ordered:
        key = (row.tool, _args_key(row.args))
        if key in seen or key in successful_keys or key not in required_keys or row.tool in PRIVATE_TOOLS:
            continue
        if row.status not in {"failed", "not_attempted"} or not row.retryable:
            continue
        if row.attempts >= MAX_ATTEMPTS:
            continue
        seen.add(key)
        candidates.append((row.tool, row.args))
        if len(candidates) >= limit:
            break
    return candidates


def required_calls(state: ResearchGraphState) -> list[RoleCall]:
    """展开每个角色的必需证据；顺序保持 assignments → requirement → tool → fund."""
    calls: list[RoleCall] = []
    for assignment in build_assignments(state):
        for requirement in assignment.required_evidence:
            codes: list[str | None] = (
                list(state.fund_codes) if requirement.scope == "per_fund" and state.fund_codes else [None]
            )
            for name in requirement.tools:
                for code in codes:
                    args = tool_args(name, code, state)
                    if args is None:
                        continue
                    calls.append(
                        RoleCall(
                            role=assignment.role,
                            requirement=requirement.label,
                            name=name,
                            args=args,
                            scope=requirement.scope,
                            fund_code=code,
                        )
                    )
    return calls
