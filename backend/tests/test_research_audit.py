"""单档与深度档共用的代码侧审计：来源完备性与引用可核对性."""

from app.agent.graph.research import report_context
from app.agent.graph.research_contract import citation_audit, completeness_note, source_completeness
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask, ResearchToolCall

PACKET = [
    {"evidence_id": "ev_a1b2c3d4e5", "tool": "get_fund_snapshot", "args": {"fund_code": "000001"}},
    {"evidence_id": "ev_0f1e2d3c4b5a", "tool": "get_fund_holdings", "args": {"fund_code": "000001"}},
]


def planned(*names: str, obtained: bool = False) -> ResearchGraphState:
    plan = [ResearchToolCall(name=name, args={"fund_code": "000001"}) for name in names]
    evidence = (
        [ResearchEvidence(tool=call.name, args=call.args, success=True, text="[TOOL_OK]", data={}) for call in plan]
        if obtained
        else []
    )
    return ResearchGraphState(turn_id="t", fund_codes=["000001", "000002"], tool_plan=plan, evidence=evidence)


class TestSourceCompleteness:
    def test_distinguishes_ok_degraded_failed_and_never_attempted(self) -> None:
        state = planned(
            "get_fund_snapshot", "get_fund_analysis_data", "get_fund_managers", "get_fund_holdings"
        ).model_copy(
            update={
                "evidence": [
                    ResearchEvidence(
                        tool="get_fund_snapshot", args={"fund_code": "000001"}, success=True, text="[TOOL_OK]", data={}
                    ),
                    ResearchEvidence(
                        tool="get_fund_analysis_data",
                        args={"fund_code": "000001"},
                        success=True,
                        text="[TOOL_OK]",
                        data={"partial": True},
                    ),
                    ResearchEvidence(
                        tool="get_fund_managers", args={"fund_code": "000001"}, success=False, text="[TOOL_ERROR]"
                    ),
                ]
            }
        )
        rows = source_completeness(state)
        assert [(row["source"], row["status"]) for row in rows] == [
            ("基金概况", "ok"),
            ("净值风险指标", "degraded"),
            ("经理资料", "failed"),
            ("披露持仓", "not_attempted"),
        ]

    def test_comparison_call_is_attributed_to_every_object(self) -> None:
        state = ResearchGraphState(
            turn_id="t",
            fund_codes=["000001", "000002"],
            tool_plan=[
                ResearchToolCall(name="get_fund_comparison_data", args={"fund_codes": ["000001", "000002"]}),
                ResearchToolCall(name="get_market_context", args={}),
            ],
        )
        rows = source_completeness(state)
        assert [(row["fund_code"], row["source"]) for row in rows] == [
            ("000001", "共同窗口数据"),
            ("000002", "共同窗口数据"),
            (None, "市场概况"),
        ]

    def test_args_must_match_to_count_as_attempted(self) -> None:
        """参数不同的同名调用不是同一份证据：另一只基金仍然算没取到."""
        state = planned("get_fund_holdings").model_copy(
            update={
                "evidence": [
                    ResearchEvidence(
                        tool="get_fund_holdings", args={"fund_code": "000002"}, success=True, text="[TOOL_OK]", data={}
                    )
                ]
            }
        )
        assert source_completeness(state)[0]["status"] == "not_attempted"


class TestCitationAudit:
    def test_counts_matched_unknown_and_uncited(self) -> None:
        text = "近一年 +12.30% [ev_a1b2c3d4e5]\n回撤 -8.40% [ev_9988776655]\n夏普 1.20"
        # 第 1 行引用可核对，第 2 行引用了不存在的 ID，第 3 行含数字但没引用。
        assert citation_audit(text, PACKET) == (1, 1, 1)

    def test_fenced_blocks_and_table_rows_are_not_required_to_cite(self) -> None:
        text = (
            "| 基金 | 近一年 |\n| --- | --- |\n| 000001 | 12.30% |\n"
            '```fund-chart\n{"fund_code": "000001", "window": "1y"}\n```\n'
            "结论依据见上表。"
        )
        assert citation_audit(text, PACKET) == (0, 0, 0)

    def test_id_pattern_is_narrow_enough_not_to_match_prose(self) -> None:
        assert citation_audit("提到 [ev_short] 与 12.30% 的份额", PACKET)[0] == 0


class TestCompletenessNote:
    def test_all_sources_ok_still_reports_the_citation_counts(self) -> None:
        note = completeness_note(
            planned("get_fund_snapshot", obtained=True), "近一年 +12.30% [ev_a1b2c3d4e5]", PACKET, "\n\n---\n\n"
        )
        assert note.startswith("\n\n---\n\n**数据来源核对**")
        assert "1 项来源全部取到" in note
        assert "1 处可核对、0 处引用了不存在的证据标识" in note

    def test_names_the_missing_source_and_object(self) -> None:
        note = completeness_note(planned("get_fund_benchmark"), "无引用文本。", PACKET, "\n\n")
        assert "000001 业绩比较基准：已计划但未取到" in note
        # 启发式计数只披露，不指控。
        assert "启发式统计，不代表编造" in note


def test_both_modes_are_told_to_cite_evidence_ids() -> None:
    """引用标记要求必须在两种模式都生效，否则单档的数字仍然无从验证."""

    def context(strategy: str) -> str:
        state = ResearchGraphState(
            turn_id="t",
            fund_codes=["000001"],
            skill_instructions="流程",
            skill_evidence="边界",
            research_task=ResearchTask(
                turn_id="t",
                request=ResearchRequest(intent="fund_research", fund_queries=["000001"], strategy=strategy),
                instruction="研究这只基金",
            ),
            tool_plan=[ResearchToolCall(name="get_fund_snapshot", args={"fund_code": "000001"})],
        )
        return report_context(state)

    for strategy in ("single", "multi_role"):
        rendered = context(strategy)
        assert "[ev_xxxx]" in rendered, strategy
        # 两种模式都拿到带 ID 的证据包，不然它没有 ID 可引。
        assert "evidence_id" in rendered, strategy
