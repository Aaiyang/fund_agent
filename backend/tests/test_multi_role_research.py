"""Communication barriers, bounded feedback, reference isolation and stream privacy."""

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import fund_selection as selection_module
from app.agent.context import dump_messages
from app.agent.graph.agent import LangGraphAgent
from app.agent.graph.agent import user_persona_service
from app.agent.graph.multi_role_research import _ROLES
from app.agent.graph.research_followup import ResearchFollowupError
from app.agent.tools.result import ToolResult
from app.core.config import settings
from app.core import session_lock
from app.core.limiter import limiter
from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from app.schemas.chat import ChatRequest, Message
from app.schemas.multi_role_research import (
    AgentAnalysis,
    AgentReport,
    DimensionStance,
    EvidenceFinding,
    ResearchActivity,
    ResearchProgress,
    ResearchReview,
    ReviewIssue,
    SupplementRequest,
    merge_agent_reports,
)


@pytest.fixture
def multi_workflow(monkeypatch):
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    state = SimpleNamespace(
        calls=[],
        analysis=[],
        reviews=[],
        reports=[],
        failures=set(),
        forged=False,
        stream=False,
        personal=False,
        fail_final=False,
        fail_review=False,
        clean_review=False,
        supplement_only=False,
        challenge=False,
        fail_revision=set(),
        two_supplements=False,
        degraded_evidence=None,
        missing_risk_metrics=False,
        fail_once=set(),
        fail_roles_once=set(),
        forged_revision=False,
        forge_roles=("risk",),
        stances={},
    )
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    state.agent = agent

    async def search(keyword):
        return [SimpleNamespace(fund_code=keyword, fund_name="已确认基金", fund_type="混合型")]

    monkeypatch.setattr(selection_module.fund_service, "search_analysis_candidates", AsyncMock(side_effect=search))

    def tool(name):
        async def invoke(args):
            state.calls.append((name, args))
            if name in state.fail_once:
                state.fail_once.remove(name)
                return ToolResult.fail("UPSTREAM_ERROR", "暂时不可用", retryable=True).to_text()
            data = {"fund_code": args.get("fund_code"), "as_of": "2026-10-09"}
            if name == "get_portfolio_snapshot":
                data = {
                    "summary": {
                        "fund_count": 1 if state.personal else 0,
                        "total_market_value": 100 if state.personal else 0,
                    },
                    "positions": [{"fund_code": "000001", "market_value": 100}] if state.personal else [],
                    "warnings": [],
                }
            if name == "get_fund_analysis_data":
                data.update(
                    {
                        "raw_count": 250,
                        "valid_daily_count": 250,
                        "partial": state.degraded_evidence == "partial",
                        "metrics": {
                            "observed_max_drawdown_ratio": None if state.missing_risk_metrics else -0.1,
                            "annualized_nav_volatility_ratio": None if state.missing_risk_metrics else 0.2,
                        },
                    }
                )
            if name == "get_fund_benchmark":
                data.update({"benchmark_text": "沪深300指数收益率", "parts": [{"weight_pp": 100}]})
            return ToolResult.ok(
                data, source="test", stale=name == "get_fund_snapshot" and state.degraded_evidence == "stale"
            ).to_text()

        return SimpleNamespace(ainvoke=invoke)

    for name in (
        "get_portfolio_snapshot",
        "get_fund_snapshot",
        "get_fund_analysis_data",
        "get_fund_benchmark",
        "get_fund_comparison_data",
        "get_fund_holdings",
        "get_fund_managers",
        "get_fund_announcements",
        "get_fund_sectors",
        "get_market_context",
        "get_market_events",
    ):
        agent.tools_by_name[name] = tool(name)

    barrier = asyncio.Event()

    async def respond(messages, **kwargs):
        schema = kwargs.get("response_format")
        if schema is None:
            if state.fail_final:
                state.fail_final = False
                raise RuntimeError("fake report failure")
            state.reports.append(messages)
            return AIMessage(content="综合报告：已核验依据、分歧与适用条件。")
        data = json.loads(messages[-1].content)
        if state.stream:
            # Real nested LLM callbacks produce tokens; none may reach the public answer.
            await FakeListChatModel(responses=["PRIVATE_AGENT_OUTPUT"]).ainvoke(messages)
        if state.stream and kwargs.get("on_text") is not None:
            # 思考片段只进观察器：换行用来验证界面那一行会被压成单行。
            kwargs["on_text"]("先核净值\n再算回撤")
            kwargs["on_text"]("区间")
        if schema is ResearchReview:
            assert len([item for item in state.analysis if not item[1]]) == len(_ROLES) - (0 if state.personal else 1)
            assert len(data["peer_reports"]) == len(_ROLES)  # 含 skipped 信封：每个维度都要有结局
            state.reviews.append(data)
            if state.fail_review:
                raise RuntimeError("fake review failure")
            if state.clean_review:
                return ResearchReview()
            if state.supplement_only:
                return ResearchReview(supplements=[SupplementRequest(kind="market_events", reason="核验更多市场事件")])
            if state.challenge:
                peer = {item["role"]: item for item in data["peer_reports"]}
                challenger_ids = list(peer["risk"]["findings"][0]["evidence_ids"])[:3]
                return ResearchReview(
                    issues=[
                        ReviewIssue(
                            role="performance",
                            finding_index=0,
                            reason="同一窗口的风险调整后结论与风险维度相反",
                            evidence_ids=peer["performance"]["findings"][0]["evidence_ids"][:6],
                            challenger_role="performance" if state.challenge == "invalid" else "risk",
                            challenger_finding_index=0,
                            challenger_evidence_ids=challenger_ids,
                        )
                    ]
                )
            return ResearchReview(
                issues=[ReviewIssue(role="manager", finding_index=0, reason="说明假设差异")],
                supplements=[
                    SupplementRequest(kind="announcements", fund_code="000001", reason="核验更多公告"),
                    SupplementRequest(
                        kind="managers",
                        fund_code="000001" if state.two_supplements else "999999",
                        reason="核验经理或拒绝越界",
                    ),
                ],
            )
        # 载荷里的 assignments 已按角色过滤，取第一条就是本次的角色；比嗅提示词稳。
        role = data["assignments"][0]["role"]
        feedback = "peer_reports" in data
        state.analysis.append((role, feedback, data))
        if not feedback:
            assert "peer_reports" not in data
            if len([item for item in state.analysis if not item[1]]) == len(_ROLES) - (0 if state.personal else 1):
                barrier.set()
            await asyncio.wait_for(barrier.wait(), timeout=2)
        else:
            assert len(data["peer_reports"]) == len(_ROLES)  # 含 skipped 信封：每个维度都要有结局
            if not state.fail_review and not state.supplement_only and not state.clean_review and not state.challenge:
                assert data["review"]["issues"][0]["role"] == "manager"
            assert all(item["fund_code"] != "999999" for item in data["review"]["supplements"])
        if role in state.fail_roles_once:
            state.fail_roles_once.remove(role)
            raise RuntimeError("fake transient role failure")
        if role in state.failures or (feedback and role in state.fail_revision):
            raise RuntimeError("fake role failure")
        findings = []
        for assignment in data["assignments"]:
            refs = []
            for requirement in assignment["required_evidence"]:
                # per_fund 要求每个确认对象都被引到一次；global 只要引到就算。
                targets = data["fund_codes"] if requirement["scope"] == "per_fund" else [None]
                for code in targets:
                    match = next(
                        (
                            entry
                            for entry in data["evidence"]
                            if entry["tool"] in requirement["tools"]
                            and (
                                code is None
                                or entry["args"].get("fund_code") == code
                                or code in entry["args"].get("fund_codes", [])
                            )
                        ),
                        None,
                    )
                    if match:
                        refs.append(match["evidence_id"])
            if not refs:
                refs = [data["evidence"][0]["evidence_id"]]
            if role in state.forge_roles and (state.forged or (feedback and state.forged_revision)):
                refs = ["ev_forged"]
            findings.append(
                EvidenceFinding(
                    claim=role + ("已回应审核反馈" if feedback else "独立发现"),
                    kind="inference",
                    evidence_ids=list(dict.fromkeys(refs))[:6],
                    limitation="历史披露，不能保证未来表现",
                )
            )
        marker = state.stances.get(role)
        stance = (
            DimensionStance(
                verdict=f"{role}的仓位立场",
                marker=marker,
                topic="position_size",
                condition="回撤收窄则改变",
                evidence_ids=[findings[0].evidence_ids[0]],
            )
            if marker
            else None
        )
        return AgentAnalysis(
            findings=findings,
            addressed_issue_indices=data.get("required_issue_indices", []),
            stance=stance,
        )

    agent.llm_service = SimpleNamespace(get_llm=lambda: None, call=respond)
    return state


# 首轮实际会调模型的专业维度；portfolio 只在有已核验持仓时才设立任务。
ROUND_ONE_ROLES = ("performance", "risk", "holdings", "manager", "disclosure")


async def basic_report(state, session="research-a"):
    answer = await state.agent.get_response([Message(role="user", content="分析000001")], session, user_id="42")
    assert answer[-1].research_id is not None
    # 追问按钮的文案要说清研究对象（研究 vs 对比），靠服务端回传的这个字段，不是猜正文。
    assert answer[-1].research_intent == "fund_research"
    return answer[-1].research_id


async def saved_state(state, session="research-a"):
    return await state.agent._graph.aget_state({"configurable": {"thread_id": session}})


def test_parallel_reducer_is_order_independent_replay_safe_and_rejects_conflicts():
    a = AgentReport(run_id="task", role="risk", round=1, status="completed")
    b = AgentReport(run_id="task", role="manager", round=1, status="completed")
    assert merge_agent_reports([a], [b, a]) == merge_agent_reports([b], [a])
    with pytest.raises(ValueError, match="conflicting"):
        merge_agent_reports([a], [a.model_copy(update={"status": "failed"})])
    with pytest.raises(ValueError, match="different runs"):
        merge_agent_reports([a], [b.model_copy(update={"run_id": "other"})])


async def test_button_reuses_confirmed_scope_and_agents_exchange_reviewed_feedback(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    # An intervening chat clears current task fields; the report reference remains valid.
    await state.agent.get_response([Message(role="user", content="你好")], "research-a", user_id="42")
    output = await state.agent.get_response(
        [Message(role="user", content="进一步研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    saved = await saved_state(state)
    assert saved.values["research_task"].source_research_id == reference
    assert saved.values["research_task"].request.mode == "deep"
    assert saved.values["research_result"].strategy == "multi_role"
    assert saved.values["research_result"].status == "partial"  # rejected reviewer target is disclosed
    assert len([item for item in state.analysis if not item[1]]) == len(ROUND_ONE_ROLES)
    assert any(item[1] for item in state.analysis)  # 审核反馈确实触发了修订轮
    assert len(state.reviews) == 1
    # 审核不再重读整包原文：只拿被真正引用到的证据摘录。
    assert "cited_evidence" in state.reviews[0] and "evidence" not in state.reviews[0]
    assert len(state.reports) == 3  # basic report, intervening chat, one final synthesis
    assert not {"agent_reports", "agent_review", "evidence"}.intersection(saved.values)
    assert not any(args.get("fund_code") == "999999" for _, args in state.calls)
    assert sum(name == "get_fund_announcements" and args.get("limit") == 10 for name, args in state.calls) == 1
    assert output[-1].research_id is None
    assert all(message.research_id is None for message in output)
    count = len(state.calls), len(state.analysis)
    await state.agent.get_response(
        [Message(role="user", content="再点一次")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    assert (len(state.calls), len(state.analysis)) == count


async def test_references_do_not_cross_sessions_or_survive_history_clear(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    with pytest.raises(ResearchFollowupError, match="research_source_not_found"):
        await state.agent.validate_research_source("other-session", reference)
    await state.agent._graph.checkpointer.adelete_thread("research-a")
    with pytest.raises(ResearchFollowupError, match="research_source_not_found"):
        await state.agent.validate_research_source("research-a", reference)


@pytest.mark.parametrize("failure", ["failed_role", "forged_reference"])
async def test_role_failure_and_forged_citations_produce_partial_report(multi_workflow, failure):
    state = multi_workflow
    if failure == "failed_role":
        state.failures.add("risk")
    else:
        state.forged = True
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="进一步研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    saved = await saved_state(state)
    assert saved.values["research_result"].status == "partial"
    context = "\n".join(str(message.content) for message in state.reports[-1])
    assert "ev_forged" not in context
    assert "风险与回撤" in str(saved.values["research_result"].gaps)


async def test_real_nested_model_tokens_are_private_and_progress_is_public(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    state.stream = True
    events = [
        item
        async for item in state.agent.get_stream_response(
            [Message(role="user", content="进一步研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        )
    ]
    text = "".join(item for item in events if isinstance(item, str))
    progress = [item for item in events if isinstance(item, ResearchProgress)]
    assert "PRIVATE_AGENT_OUTPUT" not in text
    assert text == (await state.agent.get_chat_history("research-a"))[-1].content
    assert {item.stage for item in progress} == {"evidence", "analysis", "review", "supplement", "revision", "report"}
    assert len({item.run_id for item in progress}) == 1
    assert max(i for i, item in enumerate(progress) if item.stage == "analysis") < min(
        i for i, item in enumerate(progress) if item.stage == "review"
    )


async def test_role_thinking_surfaces_as_one_line_activity_without_leaking_output(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    state.stream = True
    events = [
        item
        async for item in state.agent.get_stream_response(
            [Message(role="user", content="进一步研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        )
    ]
    activity = [item for item in events if isinstance(item, ResearchActivity)]
    pairs = {(item.role, item.stage) for item in activity}
    # 没有个人持仓时 portfolio 维度不设立，所以首轮是五个专业维度 + 审核。
    assert {("manager", "analysis"), ("risk", "analysis"), (None, "review")} <= pairs
    assert all(item.text and "\n" not in item.text for item in activity)
    assert all(item.run_id for item in activity)
    assert "PRIVATE_AGENT_OUTPUT" not in " ".join(item.text for item in activity)


async def test_report_message_carries_server_side_role_outcomes_for_the_badge(multi_workflow):
    state = multi_workflow
    state.failures.add("risk")
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="进一步研究")], "research-a", user_id="42", research_followup_id=reference
    )
    report = (await state.agent.get_chat_history("research-a"))[-1]
    # 徽标读的是服务端信封，不是模型在正文里的自述。
    assert {item.role: item.status for item in report.research_roles} == {
        "manager": "completed",
        "risk": "failed",
        "performance": "completed",
        "holdings": "completed",
        "disclosure": "completed",
        "portfolio": "skipped",
    }
    assert report.research_review_status == "partial"
    history = await state.agent.get_chat_history("research-a")
    # 徽标只属于多角色那份报告；单档位报告一个数字都不该带。
    assert all(message.research_roles is None for message in history[:-1])


async def test_explicit_multi_role_text_routes_directly_and_ordinary_deep_stays_single(multi_workflow):
    state = multi_workflow
    await state.agent.get_response([Message(role="user", content="深入分析000001")], "single", user_id="42")
    assert not state.analysis
    await state.agent.get_response([Message(role="user", content="多角色研究000001")], "research-a", user_id="42")
    assert len([item for item in state.analysis if not item[1]]) == len(ROUND_ONE_ROLES)


def test_followup_cannot_mix_attachment_or_account_scope():
    base = {"messages": [{"role": "user", "content": "进一步研究"}], "research_followup_id": "a" * 32}
    for extra in ({"holding_import_ids": ["a" * 32]}, {"holding_account_id": 12}):
        with pytest.raises(ValueError):
            ChatRequest.model_validate({**base, **extra})


def test_report_reference_is_not_forwarded_as_a_model_message_attribute():
    assert dump_messages([Message(role="user", content="研究", research_id="a" * 32)]) == [
        {"role": "user", "content": "研究"},
    ]


async def test_portfolio_role_receives_verified_positions_and_the_same_feedback(multi_workflow):
    state = multi_workflow
    state.personal = True
    output = await state.agent.get_response(
        [Message(role="user", content="诊断我的持仓")],
        "research-a",
        user_id="42",
    )
    await state.agent.get_response(
        [Message(role="user", content="进一步研究")],
        "research-a",
        user_id="42",
        research_followup_id=output[-1].research_id,
    )
    assert len([item for item in state.analysis if not item[1]]) == len(_ROLES)
    portfolio = [data for role, _, data in state.analysis if role == "portfolio"]
    # 补证取的是公告与经理资料，都不在组合适配的数据切片里，所以它不参与修订。
    assert len(portfolio) == 1
    assert all(any(item["tool"] == "get_positions" for item in data["evidence"]) for data in portfolio)


async def test_resume_after_report_failure_preserves_agent_and_tool_checkpoints(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    state.fail_final = True
    with pytest.raises(Exception, match="fake report failure"):
        await state.agent.get_response(
            [Message(role="user", content="进一步研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        )
    continuation = await state.agent.get_run_continuation("research-a")
    assert continuation is not None
    count = len(state.analysis), len(state.calls), len(state.reviews)
    with pytest.raises(ResearchFollowupError, match="agent_run_pending"):
        await state.agent.validate_research_source("research-a", reference)
    await state.agent.continue_run("research-a", continuation.turn_id, user_id="42")
    assert (len(state.analysis), len(state.calls), len(state.reviews)) == count
    assert await state.agent.get_run_continuation("research-a") is None


async def test_continuation_restarts_a_multi_role_run_whose_roles_failed(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    state.clean_review = True
    state.fail_roles_once = set(ROUND_ONE_ROLES)
    state.fail_final = True
    with pytest.raises(Exception, match="fake report failure"):
        await state.agent.get_response(
            [Message(role="user", content="多角色深度研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        )
    continuation = await state.agent.get_run_continuation("research-a")
    assert continuation is not None and "重新运行" in continuation.notice
    # 这条测试关心新开的第二轮；清掉第一轮失败记录，避免 fixture 的当前轮断言混入旧记录。
    state.analysis.clear()
    state.reviews.clear()
    await state.agent.continue_run("research-a", continuation.turn_id, user_id="42")
    report = (await state.agent.get_chat_history("research-a"))[-1]
    assert all(item.status != "failed" for item in report.research_roles)
    assert (await saved_state(state)).values["research_result"].status == "completed"
    assert await state.agent.get_run_continuation("research-a") is None


async def test_targeted_challenge_reaches_the_challenged_role_once(multi_workflow):
    state = multi_workflow
    state.challenge = "valid"
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    feedback = next(data for role, feedback, data in state.analysis if feedback and role == "performance")
    challenge = feedback["cross_examination"][0]
    assert challenge["challenger_role"] == "risk"
    assert challenge["challenger_evidence"]
    assert any("cross_examination" in str(message.content) for message in state.reports[-1])


async def test_invalid_challenge_is_dropped_without_demoting_the_issue(multi_workflow):
    state = multi_workflow
    state.challenge = "invalid"
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    feedback = next(data for role, feedback, data in state.analysis if feedback and role == "performance")
    assert "cross_examination" not in feedback
    assert feedback["review"]["issues"][0]["challenger_role"] is None


async def test_review_failure_is_disclosed_without_fabricating_a_completed_review(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    state.fail_review = True
    await state.agent.get_response(
        [Message(role="user", content="进一步研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    outcome = (await saved_state(state)).values["research_result"]
    assert outcome.status == "partial" and any("审核失败" in gap for gap in outcome.gaps)
    assert len([item for item in state.analysis if not item[1]]) == len(ROUND_ONE_ROLES)  # 审核失败不再另起一整轮分析
    assert not any(item[1] for item in state.analysis)


async def test_clean_review_reuses_complete_first_round_without_revision_calls(multi_workflow):
    state = multi_workflow
    state.clean_review = True
    reference = await basic_report(state)
    state.calls.clear()
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    assert len([item for item in state.analysis if not item[1]]) == len(ROUND_ONE_ROLES)
    assert len(state.reviews) == 1
    assert all("numeric_audit" in report for report in state.reviews[0]["peer_reports"])
    assert not any(feedback for _, feedback, _ in state.analysis)
    assert all(name != "get_portfolio_snapshot" for name, _ in state.calls)
    result = (await saved_state(state)).values["research_result"]
    assert result.status == "completed" and not result.gaps
    assert '"completed_count": 5' in "\n".join(str(message.content) for message in state.reports[-1])


async def test_upstream_missing_risk_metrics_do_not_trigger_a_revision(multi_workflow):
    state = multi_workflow
    state.clean_review = True
    state.missing_risk_metrics = True
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    assert len([item for item in state.analysis if not item[1]]) == len(ROUND_ONE_ROLES)
    assert not any(feedback for _, feedback, _ in state.analysis)
    saved = await saved_state(state)
    result = saved.values["research_result"]
    assert result.status == "partial"
    report = (await state.agent.get_chat_history("research-a"))[-1]
    assert {item.role: item.status for item in report.research_roles}["risk"] == "partial"
    assert any("净值风险指标" in line and "上游缺指标" in line for line in report.research_citations.sources)


async def test_failed_required_tool_is_retried_once_and_only_affected_role_revised(multi_workflow):
    state = multi_workflow
    state.clean_review = True
    state.fail_once = {"get_fund_benchmark"}
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    assert sum(name == "get_fund_benchmark" for name, _ in state.calls) == 2
    assert {role for role, feedback, _ in state.analysis if feedback} == {"performance"}
    assert (await saved_state(state)).values["research_result"].status == "completed"


async def test_opposite_stances_reach_the_synthesis_as_a_paired_tension(multi_workflow):
    """立场要活着穿过 derive_coverage，综合上下文里才有可转写的对立.

    单测各自覆盖了配对与成文规则，这条盯的是接缝：stance 在重建信封时被丢掉，
    上面那些测试照样全绿，而真实报告里永远不会有分歧段。
    """
    state = multi_workflow
    state.clean_review = True
    state.stances = {"risk": "oppose", "performance": "support"}
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    context = "\n".join(str(message.content) for message in state.reports[-1])
    assert '"topic_label": "仓位大小"' in context and '"revised": false' in context
    assert '"owner_a": "业绩分析师"' in context and '"owner_b": "风险分析师"' in context
    assert '"heading": "### 风险分析师｜风险与回撤"' in context, "节标题要由代码给到成文节点"


async def test_market_supplement_revises_only_the_role_that_receives_new_evidence(multi_workflow):
    state = multi_workflow
    state.supplement_only = True
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    assert [role for role, feedback, _ in state.analysis if feedback] == ["disclosure"]
    for role, _, data in state.analysis:
        if role == "manager":
            assert all(item["tool"] not in {"get_market_events", "get_positions"} for item in data["evidence"])


@pytest.mark.parametrize("streaming", [False, True])
async def test_followup_memory_search_uses_original_question_not_link_text(multi_workflow, monkeypatch, streaming):
    state = multi_workflow
    state.clean_review = True
    reference = await basic_report(state)
    memory = AsyncMock(return_value="历史用户表述")
    monkeypatch.setattr(state.agent, "_memory_snapshot", memory)
    if streaming:
        _ = [
            event
            async for event in state.agent.get_stream_response(
                [Message(role="user", content="点链接进一步研究")],
                "research-a",
                user_id="42",
                research_followup_id=reference,
            )
        ]
    else:
        await state.agent.get_response(
            [Message(role="user", content="点链接进一步研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        )
    assert memory.call_args.kwargs == {"user_id": "42", "thread_id": "research-a", "query": "分析000001"}


async def test_portfolio_role_receives_confirmed_profile_and_keeps_it_separate_from_memory(
    multi_workflow, monkeypatch
):
    state = multi_workflow
    state.personal = True
    state.clean_review = True
    monkeypatch.setattr(user_persona_service, "context", AsyncMock(return_value="已确认风险承受：低"))
    monkeypatch.setattr(state.agent, "_memory_snapshot", AsyncMock(return_value="历史表述：曾关注高风险产品"))
    await state.agent.get_response([Message(role="user", content="多角色诊断我的持仓")], "research-a", user_id="42")
    portfolio = next(data for role, _, data in state.analysis if role == "portfolio")
    assert portfolio["confirmed_user_profile"] == "已确认风险承受：低"
    assert portfolio["historical_user_statements"] == "历史表述：曾关注高风险产品"
    assert "不覆盖" in portfolio["historical_context_notice"]
    assert all("confirmed_user_profile" not in data for role, _, data in state.analysis if role != "portfolio")


async def test_unmet_evidence_requirement_is_derived_and_named(multi_workflow):
    """基准取不到时，缺哪块数据由服务端从引用算出来并写进附注；模型既不申报也不掩盖."""
    state = multi_workflow
    state.clean_review = True
    state.agent.tools_by_name["get_fund_benchmark"] = SimpleNamespace(
        ainvoke=AsyncMock(return_value="[TOOL_ERROR] 基准暂不可用")
    )
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    result = (await saved_state(state)).values["research_result"]
    assert result.status == "partial" and any("业绩比较基准" in gap for gap in result.gaps)
    assert len([item for item in state.analysis if not item[1]]) == len(ROUND_ONE_ROLES)
    # 覆盖由服务端生成：正文不再追加尾注，结构化证据里仍要说清研究对象与缺口。
    last = (await state.agent.get_chat_history("research-a"))[-1]
    coverage = "\n".join(last.research_citations.coverage) if last.research_citations else ""
    assert "研究对象：000001" in coverage and "业绩与基准契合：缺少 业绩比较基准" in coverage
    assert "待完成" not in coverage and "数据来源核对" not in last.content


@pytest.mark.parametrize("quality", ["partial", "stale"])
async def test_source_quality_cannot_be_hidden_by_agents_claiming_all_tasks_completed(multi_workflow, quality):
    state = multi_workflow
    state.clean_review = True
    state.degraded_evidence = quality
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    result = (await saved_state(state)).values["research_result"]
    assert result.status == "partial"
    marker = "数据范围或质量不完整" if quality == "partial" else "数据并非最新"
    assert any(marker in gap for gap in result.gaps)
    last = (await state.agent.get_chat_history("research-a"))[-1]
    coverage = "\n".join(last.research_citations.coverage) if last.research_citations else ""
    assert marker in coverage


async def test_revision_failure_keeps_first_round_work_and_discloses_unresolved_feedback(multi_workflow):
    state = multi_workflow
    state.fail_revision.add("manager")
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    result = (await saved_state(state)).values["research_result"]
    assert result.status == "partial" and any("基金经理与团队修订未完成" in gap for gap in result.gaps)
    context = "\n".join(str(message.content) for message in state.reports[-1])
    assert "独立发现" in context
    assert '"completed_count": 5' in context  # useful work is retained, overall review is partial


async def test_forged_revision_cannot_erase_valid_first_round_or_mark_review_resolved(multi_workflow):
    state = multi_workflow
    state.forged_revision = True
    # 审核反馈现在指向 manager；要伪造哪条结论，就得让那个角色进入修订轮。
    state.forge_roles = ("manager",)
    reference = await basic_report(state)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    outcome = (await saved_state(state)).values["research_result"]
    assert outcome.status == "partial" and any("基金经理与团队修订未完成" in gap for gap in outcome.gaps)
    context = "\n".join(str(message.content) for message in state.reports[-1])
    # 伪造的修订轮结论被整条丢弃，selected_reports 仍取首轮：好产出不会被坏修订抹掉。
    assert "ev_forged" not in context
    assert '"completed_count": 5' in context


async def test_two_supplements_are_parallel_and_return_in_stable_request_order(multi_workflow):
    state = multi_workflow
    state.two_supplements = True
    reference = await basic_report(state)
    starts = []
    ready = asyncio.Event()
    for name in ("get_fund_announcements", "get_fund_managers"):
        original = state.agent.tools_by_name[name].ainvoke

        async def slow(args, selected=name, invoke=original):
            if args["limit"] in {10, 20} and (selected != "get_fund_managers" or args["limit"] == 20):
                starts.append(selected)
                if len(starts) == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 2)  # a serial implementation fails this barrier
            return await invoke(args)

        state.agent.tools_by_name[name] = SimpleNamespace(ainvoke=slow)
    await state.agent.get_response(
        [Message(role="user", content="多角色深度研究")],
        "research-a",
        user_id="42",
        research_followup_id=reference,
    )
    assert set(starts) == {"get_fund_announcements", "get_fund_managers"}
    assert (await saved_state(state)).values["research_result"].status == "completed"


async def test_role_timeout_finishes_with_blocked_coverage_without_running_an_empty_review(
    multi_workflow, monkeypatch
):
    state = multi_workflow
    reference = await basic_report(state)
    original = state.agent.llm_service.call
    monkeypatch.setattr(settings, "MULTI_ROLE_RESEARCH_CALL_TIMEOUT", 0.05)
    monkeypatch.setattr(settings, "MULTI_ROLE_RESEARCH_TOTAL_TIMEOUT", 0.1)

    async def hang(messages, **kwargs):
        if kwargs.get("response_format") is AgentAnalysis:
            await asyncio.Event().wait()
        return await original(messages, **kwargs)

    state.agent.llm_service.call = hang
    await asyncio.wait_for(
        state.agent.get_response(
            [Message(role="user", content="多角色深度研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        ),
        timeout=3,
    )
    result = (await saved_state(state)).values["research_result"]
    assert result.status == "partial" and not state.reviews
    # 超时的维度被明确列为没做完，而不是静默消失。
    assert any("未完成有效分析" in gap or "没有可核验的发现" in gap for gap in result.gaps)


async def test_cancel_during_role_analysis_resumes_the_same_scope_without_recollecting(multi_workflow):
    state = multi_workflow
    reference = await basic_report(state)
    original = state.agent.llm_service.call
    started = asyncio.Event()

    async def hang(messages, **kwargs):
        if kwargs.get("response_format") is AgentAnalysis:
            started.set()
            await asyncio.Event().wait()
        return await original(messages, **kwargs)

    state.agent.llm_service.call = hang
    running = asyncio.create_task(
        state.agent.get_response(
            [Message(role="user", content="多角色深度研究")],
            "research-a",
            user_id="42",
            research_followup_id=reference,
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert not state.reviews and len(state.reports) == 1
    before = list(state.calls)
    continuation = await state.agent.get_run_continuation("research-a")
    assert continuation is not None and continuation.selected_fund_code == "000001"
    state.agent.llm_service.call = original
    await state.agent.continue_run("research-a", continuation.turn_id, user_id="42")
    assert state.calls[: len(before)] == before
    assert sum(name == "get_fund_snapshot" for name, _ in state.calls) == sum(
        name == "get_fund_snapshot" for name, _ in before
    )
    assert (await saved_state(state)).values["research_result"].fund_codes == ["000001"]


@pytest.mark.parametrize("missing", [False, True])
def test_api_validates_report_ownership_and_separates_progress_from_content(monkeypatch, missing):
    monkeypatch.setattr(settings, "SESSION_NAMING_ENABLED", False)
    monkeypatch.setattr(session_lock.database_service, "get_session", AsyncMock(return_value=object()))
    monkeypatch.setattr(chatbot.user_profile_service, "execution_profiles", AsyncMock(return_value=[]))
    monkeypatch.setattr(chatbot.llm_service, "use_profiles", lambda _profiles: nullcontext())
    validate = AsyncMock(side_effect=ResearchFollowupError("research_source_not_found") if missing else None)
    monkeypatch.setattr(chatbot.agent, "validate_research_source", validate)
    monkeypatch.setattr(chatbot.agent, "get_pending_holding_review", AsyncMock(return_value=None))
    monkeypatch.setattr(chatbot.agent, "get_run_continuation", AsyncMock(return_value=None))

    async def stream(messages, session_id, **kwargs):
        assert session_id == "api-research" and kwargs["user_id"] == "42"
        assert kwargs["research_followup_id"] == "a" * 32
        yield ResearchProgress(run_id="new-task", stage="review", status="started")
        yield "最终研究报告"

    monkeypatch.setattr(chatbot.agent, "get_stream_response", stream)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(chatbot.router)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        id="api-research",
        user_id=42,
        username="test",
        name=None,
    )
    with TestClient(app) as client:
        response = client.post(
            "/chat/stream",
            json={
                "messages": [{"role": "user", "content": "进一步研究"}],
                "research_followup_id": "a" * 32,
            },
        )
    if missing:
        assert response.status_code == 404 and response.json()["detail"] == "research_source_not_found"
    else:
        assert response.status_code == 200
        frames = [
            json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert frames[0]["content"] == "" and frames[0]["research_progress"]["stage"] == "review"
        assert frames[1]["content"] == "最终研究报告" and frames[-1]["done"]
        assert validate.await_count == 2  # before HTTP streaming and inside the session lock


async def test_contract_violation_gets_one_feedback_retry_then_fails_loudly(multi_workflow):
    """字段不合先回喂一次；仍不合就报契约违约，而不是伪装成"模型没做"."""
    from app.agent.graph.agent import LangGraphAgent
    from app.services.llm.timeouts import LLMContractViolation

    agent = LangGraphAgent()
    seen: list[list] = []

    async def flaky(messages, **kwargs):
        seen.append(messages)
        if len(seen) == 1:
            raise LLMContractViolation("fixture", "issues.0.role: Field required")
        return ResearchReview()

    agent.llm_service = SimpleNamespace(get_llm=lambda: None, call=flaky)  # pyright: ignore[reportAttributeAccessIssue]
    result = await agent._research_agent_call(
        "角色提示", '{"evidence": []}', ResearchReview, {"metadata": {"langgraph_node": "review_agents"}}
    )
    assert isinstance(result, ResearchReview) and len(seen) == 2
    assert "issues.0.role" in seen[-1][-1].content

    seen.clear()

    async def always_bad(messages, **kwargs):
        seen.append(messages)
        raise LLMContractViolation("fixture", "issues.0.role: Field required")

    agent.llm_service = SimpleNamespace(get_llm=lambda: None, call=always_bad)  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(LLMContractViolation):
        await agent._research_agent_call(
            "角色提示", '{"evidence": []}', ResearchReview, {"metadata": {"langgraph_node": "review_agents"}}
        )
    assert len(seen) == 2
