"""数字审计只做启发式提示，不改变覆盖或状态."""

from app.agent.graph.numeric_audit import audit_findings, tokenize_claim
from app.schemas.multi_role_research import EvidenceFinding
from app.schemas.research import ResearchEvidence


def finding(claim: str, refs: list[str]) -> EvidenceFinding:
    return EvidenceFinding(claim=claim, kind="fact", evidence_ids=refs, limitation="")


def entry(ref: str = "ev_a", tool: str = "get_fund_comparison_data", text: str = "") -> dict:
    return {"evidence_id": ref, "tool": tool, "args": {}, "text": text}


def test_ratio_and_percentage_share_one_scale() -> None:
    audit = audit_findings(
        [finding("区间收益 +46.21%，回撤 -48.43%", ["ev_a"])],
        [entry(text="window_change_ratio=0.4621")],
        [
            ResearchEvidence(
                tool="get_fund_comparison_data",
                success=True,
                text="[TOOL_OK]\n{}",
                data={"window_change_ratio": 0.4621, "observed_max_drawdown_ratio": -0.4843},
            )
        ],
    )
    assert audit.checked == 2 and audit.matched == 2 and audit.unmatched == []


def test_percentage_points_and_amounts_match_without_false_dates() -> None:
    tokens = tokenize_claim("000001 在 2026-10-21 的权重 6.45%，规模 39.38亿")
    assert [token[0] for token in tokens] == ["6.45%", "39.38亿"]
    audit = audit_findings(
        [finding("权重 6.45%，规模 39.38亿", ["ev_a"])],
        [entry(tool="get_fund_holdings")],
        [
            ResearchEvidence(
                tool="get_fund_holdings",
                success=True,
                text="[TOOL_OK]\n{}",
                data={"top_holdings": [{"weight": 6.45}], "asset_size": "39.38亿"},
            )
        ],
    )
    assert audit.matched == 2 and audit.unmatched == []


def test_derived_or_missing_number_is_reported_but_advisory() -> None:
    audit = audit_findings(
        [finding("合计约 99.99%", ["ev_a"])],
        [entry()],
        [ResearchEvidence(tool="get_fund_holdings", success=True, text="[TOOL_OK]\n{}", data={"weight": 6.45})],
    )
    assert audit.checked == 1 and audit.matched == 0
    assert audit.unmatched[0].token == "99.99%" and "启发式" in audit.note


def test_truncated_evidence_is_flagged() -> None:
    audit = audit_findings(
        [finding("收益 12.30%", ["ev_a"])],
        [entry(text="[中段已截断]")],
        [ResearchEvidence(tool="get_fund_analysis_data", success=True, text="[TOOL_OK]\n{}\n[中段已截断]")],
    )
    assert audit.truncated is True and "截断" in audit.note
