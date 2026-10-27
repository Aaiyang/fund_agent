"""从报告正文提取编号引用，并生成折叠证据所需的结构化载荷.

模型只写证据包里真实存在的 ``[ev_xxxx]``；这里按首次出现顺序生成编号，
不修改正文——流式链路会逐 token 发出原文，服务端改写会让最终正文与已发前缀
对不上。编号、来源摘录、覆盖与审计放进结构化字段，客户端把证据 ID 映射成角标。
"""

import re

from app.agent.graph.research_contract import (
    SOURCE_LABELS,
    citation_audit,
    completion_lines,
    source_completeness_lines,
)
from app.schemas.research import (
    ResearchCitationAudit,
    ResearchCitationItem,
    ResearchCitations,
    ResearchGraphState,
)

_CITATION = re.compile(r"\[(ev_[0-9a-f]{8,})\]")
_AS_OF_KEYS = (
    "as_of",
    "nav_date",
    "trade_date",
    "date",
    "quote_time",
    "published_at",
    "disclosure_date",
    "report_date",
    "updated_at",
)
_AS_OF_FIELD = re.compile(r"\bas_of\s*=\s*(20\d{2}-\d{2}-\d{2})")
_DATED_FIELD = re.compile(
    r"\b(?:nav_date|trade_date|quote_time|published_at|disclosure_date|report_date|updated_at)"
    r"\s*=\s*(20\d{2}-\d{2}-\d{2})"
)


def _outside_fences(text: str) -> list[str]:
    """围栏里的图表 JSON 不参与角标编号，也不该出现在来源列表里."""
    return [part for part in re.split(r"(```[\s\S]*?```)", text) if not part.startswith("```")]


def _fund_codes(entry: dict) -> list[str]:
    args = entry.get("args") or {}
    if not isinstance(args, dict):
        return []
    candidates = []
    single = args.get("fund_code")
    if isinstance(single, str):
        candidates.append(single)
    multiple = args.get("fund_codes")
    if isinstance(multiple, list):
        candidates.extend(item for item in multiple if isinstance(item, str))
    return list(dict.fromkeys(code for code in candidates if re.fullmatch(r"\d{6}", code)))[:3]


def _as_of(entry: dict) -> str | None:
    data = entry.get("data")
    if isinstance(data, dict):
        for key in _AS_OF_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:40]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(value)
    # 只认显式的 as_of/日期字段；工具正文里还可能出现成立日、任期起始日，
    # 拿第一个日期当数据日期会展示错误口径。
    text = str(entry.get("text") or "")
    for pattern in (_AS_OF_FIELD, _DATED_FIELD):
        found = pattern.search(text)
        if found:
            return found.group(1)
    return None


def _excerpt(entry: dict) -> str:
    """优先给工具返回的人类可读正文；只有 JSON 时退回数据行本身."""
    text = str(entry.get("text") or "")
    text = text.removeprefix("[TOOL_OK]\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and (lines[0].startswith("{") or lines[0].startswith("[")):
        data_line = lines[0]
        lines = lines[1:]
        if not lines:
            lines = [data_line]
    body = " ".join(" ".join(lines).split())
    return body[:500]


def _citation_item(entry: dict, number: int) -> ResearchCitationItem:
    tool = str(entry.get("tool") or "unknown")
    return ResearchCitationItem(
        number=number,
        evidence_id=str(entry.get("evidence_id") or ""),
        label=SOURCE_LABELS.get(tool, tool),
        tool=tool,
        fund_codes=_fund_codes(entry),
        as_of=_as_of(entry),
        excerpt=_excerpt(entry),
    )


def extract_report_citations(report_text: str, packet: list[dict]) -> list[ResearchCitationItem]:
    """按首次出现顺序给正文里真实存在的证据编号；不改写正文."""
    by_id = {str(item["evidence_id"]): item for item in packet if isinstance(item, dict) and item.get("evidence_id")}
    order: list[str] = []
    for part in _outside_fences(report_text):
        for match in _CITATION.finditer(part):
            evidence_id = match.group(1)
            if evidence_id in by_id and evidence_id not in order:
                order.append(evidence_id)
    return [_citation_item(by_id[evidence_id], index + 1) for index, evidence_id in enumerate(order)]


def build_research_citations(
    state: ResearchGraphState,
    report_text: str,
    packet: list[dict],
    citations: list[ResearchCitationItem],
    *,
    multi_role: bool,
) -> ResearchCitations:
    """把编号、覆盖、来源核对与审计收进一条消息的结构化字段."""
    matched, unknown, uncited_lines = citation_audit(report_text, packet)
    coverage = (
        completion_lines(state) if multi_role else ["研究对象：" + ("、".join(state.fund_codes) or "无确认对象")]
    )
    return ResearchCitations(
        citations=citations,
        coverage=coverage,
        sources=source_completeness_lines(state),
        audit=ResearchCitationAudit(
            matched=matched,
            unknown=unknown,
            uncited_lines=uncited_lines,
        ),
    )
