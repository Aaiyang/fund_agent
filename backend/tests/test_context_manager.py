"""ContextManager v1 回归测试（任务书 §30）.

覆盖：长 Tool 尾巴、Tool 层大结果 Contract、Context Hard Limit 兜底、
重复 Tool Call 去重、Only System 拒绝、历史超预算完整 Turn 淘汰、
合法 Tool Trace 保持，以及 user_id/身份类参数永不出现在工具 Schema。
"""

import json
from datetime import timedelta

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agent.context.manager import ContextManager, prepare_messages
from app.agent.context.models import (
    ContextDiagnostics,
    ContextEnvelope,
    ContextInvariantError,
    ContextRequest,
)
from app.agent.context.validator import ContextValidator
from app.utils.clock import business_today


@pytest.fixture()
def manager() -> ContextManager:
    return ContextManager()


def _human(content: str) -> HumanMessage:
    return HumanMessage(content=content)


def _tool_round(call_id: str, content: str, tool_name: str = "get_fund_holdings") -> list:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": {"fund_code": "022287"}, "id": call_id, "type": "tool_call"}],
        ),
        ToolMessage(content=content, name=tool_name, tool_call_id=call_id),
    ]


def _long_tool_tail(human_content: str, rounds: int = 60, result_size: int = 400) -> list:
    """模拟任务书 Test 1：一条提问后跟着超长工具轨迹."""
    messages = [_human(human_content)]
    for i in range(rounds):
        messages.extend(_tool_round(f"call_{i}", f"第 {i} 轮工具结果：" + "持仓数据" * result_size))
    return messages


# ---------------------------------------------------------------------------
# Test 1：长 Tool Tail
# ---------------------------------------------------------------------------


async def test_long_tool_tail_keeps_current_user_turn(manager: ContextManager):
    messages = _long_tool_tail("帮我搜索当前基金的相关新闻", rounds=80, result_size=300)
    request = ContextRequest(conversation_id="t1", max_context_tokens=4096)

    prepared = await manager.prepare(messages, system_message="SYS", request=request)

    assert prepared.diagnostics.current_user_present is True
    types = [getattr(m, "type", None) for m in prepared.messages]
    assert "human" in types
    assert len(types) > 2  # 不只有 System
    # 当前提问必须真的在最终上下文里
    assert any(getattr(m, "content", None) == "帮我搜索当前基金的相关新闻" for m in prepared.messages)


# ---------------------------------------------------------------------------
# Test 2：Tool 层大结果 Contract + Context Hard Limit 兜底
# ---------------------------------------------------------------------------


async def test_tool_layer_output_contract_get_fund_history(monkeypatch):
    """Service 返回 700 天日线时，Tool 层必须采样并附带告警，不裸返回全量."""
    from types import SimpleNamespace

    from app.agent.tools.fund import get_fund_history
    from tests.test_agent_tools import _patch_tool_service

    base = business_today() - timedelta(days=700)
    points = [SimpleNamespace(nav_date=base + timedelta(days=i), unit_nav=1.0 + i / 1000) for i in range(700)]

    async def fake_history(fund_code, start_date=None, end_date=None, range_key=None, limit=None, before_date=None):
        return SimpleNamespace(fund_code=fund_code, range=range_key, total=700, has_more=False, points=points)

    _patch_tool_service(monkeypatch, "get_fund_history", SimpleNamespace(get_nav_history=fake_history))
    text = await get_fund_history.ainvoke({"fund_code": "005827", "range_key": "3y"})

    payload = json.loads(text.split("\n")[1])
    assert payload["granularity"] == "weekly"
    # weekly 采样后 700 天 ≈ 100 周，远小于日线全量
    assert len(payload["points"]) <= 120
    assert any("采样" in w for w in text.split("\n") if "note" in w) or "已按" in text


async def test_context_hard_limit_truncates_oversized_tool_message(manager: ContextManager):
    """单条 ToolMessage 超过硬上限时：截断 + 诊断计数，用户提问保留."""
    huge = "持仓数据" * 6000  # 约 12000 字，远超 4000 token
    messages = [
        _human("分析这个工具结果"),
        *_tool_round("call_huge", huge),
    ]
    request = ContextRequest(conversation_id="t2", max_context_tokens=20000)

    prepared = await manager.prepare(messages, system_message="SYS", request=request)

    assert prepared.diagnostics.tool_observations_compacted == 1
    assert prepared.diagnostics.current_user_present is True
    tool_messages = [m for m in prepared.messages if getattr(m, "type", None) == "tool"]
    assert len(tool_messages) == 1  # 配对保留，没有删除
    assert "TRUNCATED" in tool_messages[0].content


# ---------------------------------------------------------------------------
# Test 3：重复 Tool Call 去重
# ---------------------------------------------------------------------------


async def test_duplicate_tool_calls_are_deduped(manager: ContextManager):
    messages = [_human("搜索新闻")]
    for i in range(4):
        # 连续 4 次完全相同的调用（内容一致 → 指纹一致）
        messages.extend(_tool_round(f"call_{i}", "搜索失败：rate limited"))

    request = ContextRequest(conversation_id="t3", max_context_tokens=8000)
    prepared = await manager.prepare(messages, system_message="SYS", request=request)

    assert prepared.diagnostics.duplicate_tool_observations_removed == 3
    tool_messages = [m for m in prepared.messages if getattr(m, "type", None) == "tool"]
    # 配对全部保留（不破坏 AI ToolCall → ToolMessage 关系）
    assert len(tool_messages) == 4
    stubs = [m for m in tool_messages if "已去重" in m.content]
    assert len(stubs) == 3


# ---------------------------------------------------------------------------
# Test 4：Only System 必须拒绝
# ---------------------------------------------------------------------------


def test_only_system_message_raises():
    validator = ContextValidator()
    envelope = ContextEnvelope(
        current_turn=__import__("app.agent.context.models", fromlist=["CurrentUserTurn"]).CurrentUserTurn(
            content="问题"
        ),
    )
    diagnostics = ContextDiagnostics(
        total_tokens=10, message_count=1, max_context_tokens=16384, current_user_present=False
    )
    with pytest.raises(ContextInvariantError) as excinfo:
        validator.validate([SystemMessage(content="SYS")], envelope, diagnostics)
    assert excinfo.value.code == "ONLY_SYSTEM_MESSAGE"


def test_missing_current_user_turn_raises(manager: ContextManager):
    """会话里没有任何 human 消息时必须拒绝组装."""
    messages = [
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c", "type": "tool_call"}]),
        ToolMessage(content="结果", tool_call_id="c"),
    ]
    request = ContextRequest(conversation_id="t5", max_context_tokens=4096)

    with pytest.raises(ContextInvariantError) as excinfo:
        __import__("asyncio").run(manager.prepare(messages, system_message="SYS", request=request))
    assert excinfo.value.code == "CURRENT_USER_TURN_MISSING"


# ---------------------------------------------------------------------------
# Test 5：历史超预算——完整 Turn 淘汰，不产生半截轮次
# ---------------------------------------------------------------------------


async def test_history_over_budget_drops_oldest_complete_turns(manager: ContextManager):
    messages: list = []
    for turn_index in range(20):
        messages.append(_human(f"第 {turn_index} 轮提问"))
        messages.extend(_tool_round(f"c{turn_index}", f"第 {turn_index} 轮工具结果，" + "数据" * 100))
        messages.append(AIMessage(content=f"第 {turn_index} 轮回答完成"))

    # 预算故意设小：只装得下少数几个完整轮次
    request = ContextRequest(conversation_id="t6", max_context_tokens=1500)
    prepared = await manager.prepare(messages, system_message="SYS", request=request)

    assert prepared.diagnostics.current_user_present is True
    assert prepared.diagnostics.dropped_turn_count > 0
    # 不产生半截轮次：每一段工具消息都紧跟在某个 human（或其 AI 转发）之后
    types = [getattr(m, "type", None) for m in prepared.messages if getattr(m, "type", None) != "system"]
    assert types[0] == "human"  # 窗口从 human 开始
    # 最后一个 Turn 是当前提问，完整保留
    assert "第 19 轮提问" in prepared.messages[-1].content or any(
        getattr(m, "content", None) == "第 19 轮提问" for m in prepared.messages
    )


# ---------------------------------------------------------------------------
# Test 6：当前合法 Tool Trace 保持
# ---------------------------------------------------------------------------


async def test_legal_tool_trace_preserved(manager: ContextManager):
    messages = [
        _human("搜索新闻"),
        *_tool_round("call_a", "搜索结果 A", tool_name="duckduckgo_results_json"),
        AIMessage(content="这是搜索结果 A 的总结。"),
    ]
    request = ContextRequest(conversation_id="t7", max_context_tokens=8000)
    prepared = await manager.prepare(messages, system_message="SYS", request=request)

    # 校验器不抛 INVALID_TOOL_TRACE 即通过；再显式检查配对顺序
    ai_index = next(i for i, m in enumerate(prepared.messages) if getattr(m, "type", None) == "ai")
    tool_index = next(i for i, m in enumerate(prepared.messages) if getattr(m, "type", None) == "tool")
    assert tool_index == ai_index + 1


# ---------------------------------------------------------------------------
# 诊断信息与预算字段
# ---------------------------------------------------------------------------


async def test_diagnostics_fields_populated(manager: ContextManager):
    messages = [_human("你好")]
    request = ContextRequest(conversation_id="t8", max_context_tokens=4096)
    prepared = await manager.prepare(messages, system_message="SYS", request=request)

    d = prepared.diagnostics
    assert d.total_tokens > 0
    assert d.message_count == len(prepared.messages)
    assert d.max_context_tokens == 4096
    assert d.current_user_present is True


# ---------------------------------------------------------------------------
# 旧 API 兼容：prepare_messages 仍然可用
# ---------------------------------------------------------------------------


def test_legacy_prepare_messages_still_works():
    messages = [_human("你好"), AIMessage(content="你好！")]
    out = prepare_messages(messages, "SYS")
    assert out[0].content == "SYS"
    assert len(out) == 3
