"""服务端数字审计：检查角色结论里的数值能否在它引用的证据中找到.

审计是启发式提示，不改变覆盖、状态或缺口；派生和、百分比四舍五入、单位差异都可能
产生未命中，因此只把未命中交给审核员参考，不能据此直接判结论错误。
"""

import json
import math
import re
from typing import Any

from app.schemas.multi_role_research import EvidenceFinding, NumericAudit, NumericMismatch
from app.schemas.research import ResearchEvidence

_PERCENT = re.compile(r"(?<![\d.])([+\-−]?\d+(?:\.\d+)?)\s*[%％]")
_AMOUNT = re.compile(r"(?<![\d.])([+\-−]?\d+(?:\.\d+)?)\s*(亿元|亿|万元|万|元|倍|个百分点|pp)")
_DECIMAL = re.compile(r"(?<![\d.])([+\-−]?\d+\.\d{2,})(?![\d.])")
_TRUNCATED = "[中段已截断"
_UNIT_MULTIPLIER = {"亿元": 1e8, "亿": 1e8, "万元": 1e4, "万": 1e4, "元": 1.0, "倍": 1.0, "个百分点": 1.0, "pp": 1.0}


def _number(value: str) -> float | None:
    cleaned = value.replace("−", "-").replace("＋", "+").strip()
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def tokenize_claim(text: str) -> list[tuple[str, str, tuple[float, ...]]]:
    """提取需要核对的数值；返回 (原文, 类型, 可比较候选)."""
    tokens: list[tuple[str, str, tuple[float, ...]]] = []
    spans: list[tuple[int, int]] = []
    for pattern, kind in ((_PERCENT, "percent"), (_AMOUNT, "amount")):
        for match in pattern.finditer(text):
            value = _number(match.group(1))
            if value is None:
                continue
            spans.append(match.span())
            if kind == "percent":
                # 证据可能存 ratio（0.4621）或百分点（46.21），两种都接受。
                candidates = (value, value / 100)
            else:
                unit = match.group(2)
                multiplier = _UNIT_MULTIPLIER.get(unit, 1.0)
                candidates = (value * multiplier, value)
            tokens.append((match.group(0).strip(), kind, candidates))
    for match in _DECIMAL.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        value = _number(match.group(1))
        if value is None:
            continue
        # 跳过 2026.10 这类被当成小数的日期/年份。
        if 1900 <= abs(value) <= 2100 and abs(value) == int(abs(value)):
            continue
        tokens.append((match.group(0).strip(), "decimal", (value,)))
    return tokens


def _append_number(values: list[float], value: int | float) -> None:
    number = float(value)
    if not math.isfinite(number):
        return
    values.append(number)
    values.append(number / 100)


def _collect_values(value: Any, values: list[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        _append_number(values, value)
        return
    if isinstance(value, str):
        for token, kind, candidates in tokenize_claim(value):
            del token, kind
            values.extend(candidates)
        return
    if isinstance(value, dict):
        for child in value.values():
            _collect_values(child, values)
        return
    if isinstance(value, list):
        for child in value:
            _collect_values(child, values)


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-6, abs(right) * 0.005)


def _matches(candidates: tuple[float, ...], values: list[float]) -> bool:
    return any(_close(candidate, value) for candidate in candidates for value in values)


def audit_findings(
    findings: list[EvidenceFinding],
    packet: list[dict],
    evidence: list[ResearchEvidence],
) -> NumericAudit:
    """按 finding 的引用并集核对数字；未命中最多保留 5 条，供审核参考."""
    by_id = {str(item.get("evidence_id")): item for item in packet if item.get("evidence_id")}
    by_key = {
        (item.tool, json.dumps(item.args or {}, sort_keys=True, ensure_ascii=False, default=str)): item
        for item in evidence
        if item.success
    }
    checked = 0
    matched = 0
    unmatched: list[NumericMismatch] = []
    truncated = False
    for index, finding in enumerate(findings):
        cited_values: list[float] = []
        for evidence_id in finding.evidence_ids:
            entry = by_id.get(evidence_id)
            if entry is None:
                continue
            key = (
                str(entry.get("tool") or ""),
                json.dumps(entry.get("args") or {}, sort_keys=True, ensure_ascii=False, default=str),
            )
            item = by_key.get(key)
            _collect_values(item.data if item is not None else None, cited_values)
            text = item.text if item is not None else str(entry.get("text") or "")
            if _TRUNCATED in text:
                truncated = True
            _collect_values(text, cited_values)
        for token, _kind, candidates in tokenize_claim(finding.claim):
            checked += 1
            if _matches(candidates, cited_values):
                matched += 1
            elif len(unmatched) < 5:
                unmatched.append(
                    NumericMismatch(
                        finding_index=index,
                        token=token,
                        reason="引用的证据中未找到该数值（可能是派生值或单位差异）",
                    )
                )
    note = "启发式提示：未命中不代表编造，派生计算、四舍五入或单位差异也可能未命中。"
    if truncated:
        note += " 部分证据正文有截断，已优先使用结构化数据核对。"
    return NumericAudit(checked=checked, matched=matched, unmatched=unmatched, truncated=truncated, note=note)
