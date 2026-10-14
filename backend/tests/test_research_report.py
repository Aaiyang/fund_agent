"""报告被长度截断时接续正文，耗尽预算时保持任务未完成."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph.report_generation import generate_research_report
from app.core.config import settings
from app.services.llm.registry import _new_chat_model
from app.services.llm.timeouts import LLMResponseInterrupted


async def test_length_truncation_continues_same_report_and_preserves_evidence():
    messages = [HumanMessage(content="可信证据：净值来自 fixture，请输出完整研究。")]
    first = AIMessage(
        content="## 风险\n需要核",
        response_metadata={"finish_reason": "length"},
        usage_metadata={"input_tokens": 5, "output_tokens": 10, "total_tokens": 15},
    )
    last = AIMessage(
        content="验持仓日期。\n## 来源\nfixture。",
        response_metadata={"finish_reason": "stop"},
        usage_metadata={"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
    )
    call = AsyncMock(side_effect=[first, last])
    report = await generate_research_report(messages, call)
    assert report.content == first.content + last.content
    assert report.response_metadata == {"finish_reason": "stop", "report_continuations": 1}
    assert report.usage_metadata == {"input_tokens": 25, "output_tokens": 40, "total_tokens": 65}
    followup = call.call_args_list[1].args[0]
    assert followup[0] is messages[0] and followup[1].content == first.content
    assert "请勿重复" in followup[-1].content
    assert call.call_args_list[0].kwargs["max_tokens"] == settings.RESEARCH_REPORT_MAX_TOKENS


async def test_reasoning_only_length_response_can_be_followed_by_a_complete_report():
    call = AsyncMock(
        side_effect=[
            AIMessage(content="", response_metadata={"finish_reason": "length"}),
            AIMessage(content="完整报告。", response_metadata={"finish_reason": "stop"}),
        ]
    )
    report = await generate_research_report([HumanMessage(content="研究")], call)
    assert report.content == "完整报告。"
    assert not any(isinstance(item, AIMessage) for item in call.call_args_list[1].args[0])


async def test_continuation_budget_exhaustion_does_not_return_a_completed_report(monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_REPORT_MAX_CONTINUATIONS", 1)
    call = AsyncMock(return_value=AIMessage(content="未完成", response_metadata={"finish_reason": "length"}))
    with pytest.raises(LLMResponseInterrupted, match="尚未完整生成"):
        await generate_research_report([HumanMessage(content="研究")], call)
    assert call.await_count == 2


async def test_empty_completed_response_does_not_complete_research():
    with pytest.raises(LLMResponseInterrupted, match="未返回报告正文"):
        await generate_research_report([HumanMessage(content="研究")], AsyncMock(return_value=AIMessage(content="")))


async def test_total_deadline_covers_all_continuations(monkeypatch):
    monkeypatch.setattr(settings, "LLM_TOTAL_TIMEOUT", 0.05)

    async def call(*args, **kwargs):
        await asyncio.sleep(0.03)
        return AIMessage(content="未完成", response_metadata={"finish_reason": "length"})

    with pytest.raises(LLMResponseInterrupted) as error:
        await generate_research_report([HumanMessage(content="研究")], call)
    assert error.value.reason == "total"


@pytest.mark.parametrize("model", ["glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"])
def test_glm_calls_get_the_configured_reasoning_effort_without_disabling_thinking(model):
    # 思考 token 计入 max_tokens，所以每一类调用都要压档位：只压报告会让角色调用被截成空正文。
    report = _new_chat_model(model, "fixture", "https://fixture.invalid/v1", max_tokens=16384)
    plain = _new_chat_model(model, "fixture", "https://fixture.invalid/v1")
    assert report.extra_body == {"max_tokens": 16384, "reasoning_effort": settings.LLM_REASONING_EFFORT}
    assert plain.extra_body == {"max_tokens": settings.MAX_TOKENS, "reasoning_effort": settings.LLM_REASONING_EFFORT}


def test_unknown_report_provider_does_not_receive_glm_options():
    report = _new_chat_model("another-model", "fixture", "https://fixture.invalid/v1")
    assert report.extra_body == {"max_tokens": settings.MAX_TOKENS}
