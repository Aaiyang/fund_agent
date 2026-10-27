"""报告引用编号：内部 evidence_id 转角标、来源摘录、覆盖与审计."""

from app.agent.graph.citation_report import build_research_citations, extract_report_citations
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchToolCall

A = "ev_aaaaaaaaaaaaaaaa"
B = "ev_bbbbbbbbbbbbbbbb"
C = "ev_cccccccccccccccc"
D = "ev_dddddddddddddddd"
PACKET = [
    {
        "evidence_id": A,
        "tool": "get_fund_snapshot",
        "args": {"fund_code": "000001"},
        "success": True,
        "text": '[TOOL_OK]\n{"as_of": "2026-10-20"}\n近一年净值上涨 12.30%',
        "data": {"as_of": "2026-10-20"},
    },
    {
        "evidence_id": B,
        "tool": "get_fund_holdings",
        "args": {"fund_code": "000001"},
        "success": True,
        "text": '[TOOL_OK]\n{"report_date": "2026-06-30"}\n前十大持仓占比 58.20%',
        "data": {"report_date": "2026-06-30"},
    },
    {
        "evidence_id": D,
        "tool": "get_fund_sectors",
        "args": {"fund_code": "000001"},
        "success": True,
        "text": "[TOOL_OK]\n{}",
        "data": {},
    },
]


def test_known_sources_are_numbered_by_first_appearance_and_fences_are_ignored() -> None:
    text = (
        "近一年上涨 12.30% [ev_aaaaaaaaaaaaaaaa]。\n"
        '```fund-chart\n{"fund_code": "000001", "raw": "' + D + '"}\n```\n'
        "披露持仓集中度 58.20% [ev_bbbbbbbbbbbbbbbb]，收益再次确认 [ev_aaaaaaaaaaaaaaaa]。\n"
        "无来源指认 [ev_cccccccccccccccc]。\n\n---\n\n**数据来源核对**\n旧尾注不应出现。"
    )
    citations = extract_report_citations(text, PACKET)

    assert [(item.number, item.evidence_id) for item in citations] == [(1, A), (2, B)]
    assert citations[0].label == "基金概况"
    assert citations[0].fund_codes == ["000001"] and citations[0].as_of == "2026-10-20"
    assert "12.30%" in citations[0].excerpt and "[TOOL_OK]" not in citations[0].excerpt
    assert citations[1].label == "披露持仓" and citations[1].as_of == "2026-06-30"
    # 围栏里的证据 ID 不占号，哪怕它在证据包里真实存在。
    assert all(item.evidence_id != D for item in citations)


def test_payload_carries_coverage_sources_and_audit_without_touching_the_visible_report() -> None:
    state = ResearchGraphState(
        turn_id="t",
        fund_codes=["000001"],
        tool_plan=[ResearchToolCall(name="get_fund_snapshot", args={"fund_code": "000001"})],
        evidence=[
            ResearchEvidence(
                tool="get_fund_snapshot",
                args={"fund_code": "000001"},
                success=True,
                text="[TOOL_OK]\n{}",
                data={},
            )
        ],
    )
    text = "近一年上涨 12.30% [ev_aaaaaaaaaaaaaaaa]。\n另有一天 1.20% 没有引用。"
    citations = extract_report_citations(text, PACKET)
    payload = build_research_citations(state, text, PACKET, citations, multi_role=False)

    assert [(item.number, item.evidence_id) for item in citations] == [(1, A)]
    assert payload.coverage == ["研究对象：000001"]
    assert payload.sources == ["本轮计划的 1 项来源全部取到。"]
    assert payload.audit.matched == 1 and payload.audit.unknown == 0
    assert payload.audit.uncited_lines == 1


def test_as_of_uses_explicit_fields_and_never_random_dates_in_the_text() -> None:
    entry = {
        "evidence_id": A,
        "tool": "get_fund_snapshot",
        "args": {"fund_code": "000001"},
        "success": True,
        "text": "[TOOL_OK]\n{}\n成立日期 2001-12-18; as_of=2026-10-16; source=akshare",
        "data": {},
    }
    citations = extract_report_citations("结论 [ev_aaaaaaaaaaaaaaaa]", [entry])
    assert citations[0].as_of == "2026-10-16"

    no_explicit = {**entry, "text": "[TOOL_OK]\n{}\n成立日期 2001-12-18; 任期从 2024-12-26 开始"}
    citations = extract_report_citations("结论 [ev_aaaaaaaaaaaaaaaa]", [no_explicit])
    assert citations[0].as_of is None


def test_unknown_ids_are_not_numbered_and_are_audited() -> None:
    text = "结论 12.30% [ev_ffffffffffffffff]。"
    citations = extract_report_citations(text, PACKET)
    payload = build_research_citations(
        ResearchGraphState(turn_id="t", fund_codes=[]),
        text,
        PACKET,
        citations,
        multi_role=False,
    )

    assert citations == []
    assert payload.audit.unknown == 1 and payload.audit.matched == 0
    assert payload.coverage == ["研究对象：无确认对象"]
