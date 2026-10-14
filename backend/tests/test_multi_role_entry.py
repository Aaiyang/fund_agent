"""客户端选基金面板直接授权研究的入口校验.

入口的授权来源有三种：模型提出的 start_research（要逐字段过本轮原文取证）、
报告按钮的追问（followup）、以及选基金面板（client）。后两种由服务端
构造任务，共用 route_task 的同一道放行口。
"""

import pytest
from typing import Literal
from pydantic import ValidationError

from app.agent.graph.task_router import route_task
from app.schemas.chat import ChatInputMessage, ChatRequest
from app.schemas.graph import GraphState
from app.schemas.research import ResearchRequest, ResearchTask
from app.utils.task_routing import client_research_request


def test_client_request_locks_strategy_and_depth() -> None:
    # 便宜的档位：一次模型出报告，但仍是 deep 取证
    assert client_research_request(["022287"], "single") == ResearchRequest(
        intent="fund_research", fund_queries=["022287"], mode="deep", strategy="single"
    )
    assert client_research_request(["022287"], "multi_role").strategy == "multi_role"
    assert client_research_request(["022287", "000001"], "multi_role").intent == "fund_comparison"


def test_client_request_rejects_more_than_three_funds() -> None:
    with pytest.raises(ValueError, match="最多研究三只"):
        client_research_request(["000001", "000002", "000003", "000004"], "single")


MESSAGES = [ChatInputMessage(role="user", content="多智能体分析")]


def test_chat_request_accepts_only_six_digit_codes() -> None:
    assert ChatRequest(messages=MESSAGES, research_fund_codes=["022287"]).research_fund_codes == ["022287"]
    for codes in (["22287"], ["0222871"], ["0222 87"], ["022287"] * 2, ["000001", "000002", "000003", "000004"]):
        with pytest.raises(ValidationError):
            ChatRequest(messages=MESSAGES, research_fund_codes=codes)


def test_chat_request_rejects_mixing_research_with_attachments_or_followup() -> None:
    with pytest.raises(ValidationError, match="单独提交"):
        ChatRequest(messages=MESSAGES, research_fund_codes=["022287"], holding_import_ids=["a" * 32])
    with pytest.raises(ValidationError, match="单独提交"):
        ChatRequest(messages=MESSAGES, research_fund_codes=["022287"], holding_account_id=3)
    with pytest.raises(ValidationError, match="单独提交"):
        ChatRequest(messages=MESSAGES, research_fund_codes=["022287"], research_followup_id="b" * 32)


def test_expensive_tier_cannot_be_declared_without_targets() -> None:
    # 只声明 multi_role 不给代码：不能凭空拉起三角色合议
    with pytest.raises(ValidationError, match="需要同时给出研究对象代码"):
        ChatRequest(messages=MESSAGES, research_strategy="multi_role")


def _state(requested_by: Literal["model", "followup", "client"]) -> GraphState:
    task = ResearchTask(
        turn_id="turn-1",
        request=client_research_request(["022287"], "multi_role"),
        instruction="多智能体分析",
        requested_by=requested_by,
    )
    return GraphState.model_validate(
        {"messages": [{"role": "user", "content": "多智能体分析"}], "turn_id": "turn-1", "research_task": task}
    )


def test_client_task_uses_the_server_authorized_fast_path() -> None:
    command = route_task(_state("client"))
    assert command.goto == "continue_research"
    assert not command.update


def test_followup_task_still_uses_the_same_seam() -> None:
    assert route_task(_state("followup")).goto == "continue_research"


def test_model_proposed_task_still_needs_provenance_checks() -> None:
    # 默认 requested_by=model：预置任务不能绕过逐项原文取证
    assert route_task(_state("model")).goto == "chat"
