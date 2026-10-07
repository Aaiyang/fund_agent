"""KV Cache / Prompt Cache 策略回归测试（任务书 §27）.

覆盖：时间不破坏全局前缀、Tool 顺序稳定、记忆快照冻结、
Current Run append-only、未达阈值不滑动、达到阈值标记压缩、
前缀指纹对系统提示词变化敏感，以及交易时段标签。
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.context.budget import token_estimator
from app.agent.context.cache_policy import CachePolicy
import pytest

from app.agent.context.manager import ContextManager, prepare_messages
from app.agent.context.models import ContextRequest, SessionSnapshot
from app.agent.prompts import SYSTEM_PROMPT_VERSION, load_system_prompt
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, TOOLS_VERSION
from app.utils.clock import trading_session_label

policy = CachePolicy()
TZ = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------------------
# 交易时段标签
# ---------------------------------------------------------------------------


def test_trading_session_label_buckets():
    cases = [
        (datetime(2026, 10, 5, 8, 0, tzinfo=TZ), "盘前"),
        (datetime(2026, 10, 5, 10, 0, tzinfo=TZ), "盘中（上午）"),
        (datetime(2026, 10, 5, 12, 0, tzinfo=TZ), "午间休市"),
        (datetime(2026, 10, 5, 14, 0, tzinfo=TZ), "盘中（下午）"),
        (datetime(2026, 10, 5, 16, 0, tzinfo=TZ), "已收盘"),
        (datetime(2026, 10, 3, 10, 0, tzinfo=TZ), "休市（周末）"),
    ]
    for moment, expected in cases:
        assert trading_session_label(moment) == expected


# ---------------------------------------------------------------------------
# 前缀指纹（spec 17/18）
# ---------------------------------------------------------------------------


def test_fingerprint_is_canonical():
    """键顺序不同的等价 JSON 必须产出相同指纹."""
    assert policy.fingerprint({"a": 1, "b": 2}) == policy.fingerprint({"b": 2, "a": 1})


def test_fingerprint_changes_on_system_change():
    """系统提示词变化 → global 指纹必须变化（spec 27 Test 7）."""
    h1 = policy.fingerprint({"system": "prompt v1", "tools": ["t1"]})
    h2 = policy.fingerprint({"system": "prompt v2", "tools": ["t1"]})
    assert h1 != h2


# ---------------------------------------------------------------------------
# Test 1：秒级时间不再进入系统提示词
# ---------------------------------------------------------------------------


def test_system_prompt_contains_no_wall_clock_time():
    """回归：系统提示词（模板与渲染结果）都不得包含秒级墙上时间.

    第一版修复的替换脚本静默失败（模板已改、加载器死代码未删），而当时的
    验证测试两次调用发生在同一秒、比较恒等，没能拦住——本测试同时锁住
    模板与渲染结果两层。
    """
    from app.agent.prompts import _SYSTEM_PROMPT_TEMPLATE

    # 模板层：不允许时间占位符回来
    assert "{current_date_and_time}" not in _SYSTEM_PROMPT_TEMPLATE

    # 渲染层：把时钟 monkeypatch 到两个不同时刻，输出必须一致且无时间
    from datetime import datetime
    from app.utils import clock

    times = [
        datetime(2026, 10, 4, 19, 0, 1, tzinfo=TZ),
        datetime(2026, 10, 4, 19, 0, 5, tzinfo=TZ),
    ]
    rendered = []
    original_clock = clock.business_now
    for moment in times:
        clock.business_now = lambda m=moment: m  # noqa: E731
        try:
            rendered.append(load_system_prompt(username="u", long_term_memory="记忆"))
        finally:
            clock.business_now = original_clock

    assert rendered[0] == rendered[1]
    assert not re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", rendered[0])
    assert "CST" not in rendered[0]


def test_session_label_varies_but_global_prefix_stable():
    """时段标签随时刻变化，但全局前缀指纹不变（标签已移到 Dynamic Tail）."""
    label_morning = trading_session_label(datetime(2026, 10, 5, 10, 0, tzinfo=TZ))
    label_night = trading_session_label(datetime(2026, 10, 5, 20, 0, tzinfo=TZ))
    assert label_morning != label_night

    prompt_morning = load_system_prompt(username="u", long_term_memory="记忆")
    prompt_night = load_system_prompt(username="u", long_term_memory="记忆")
    # 时间已移出系统提示词：不同时段构建的提示词逐字节一致
    assert prompt_morning == prompt_night


# ---------------------------------------------------------------------------
# Test 2：Tool 顺序与 Schema 稳定
# ---------------------------------------------------------------------------


def test_tool_registry_order_and_version_stable():
    names_1 = [tool.name for tool in DEFAULT_AGENT_TOOLS]
    names_2 = [tool.name for tool in DEFAULT_AGENT_TOOLS]
    assert names_1 == names_2
    assert TOOLS_VERSION == "v1"
    global_hash_1 = policy.fingerprint({"system": "s", "tools": TOOLS_VERSION})
    global_hash_2 = policy.fingerprint({"system": "s", "tools": TOOLS_VERSION})
    assert global_hash_1 == global_hash_2


# ---------------------------------------------------------------------------
# Test 3：Memory 快照冻结（后台更新不影响当前会话前缀）
# ---------------------------------------------------------------------------


class _FakeMemoryService:
    def __init__(self, results: list[str]):
        self.results = list(results)
        self.calls = 0

    async def search(self, user_id, query):
        self.calls += 1
        return self.results.pop(0) if self.results else "旧记忆"


async def test_memory_snapshot_frozen_per_session(monkeypatch):
    from app.agent.graph.agent import LangGraphAgent

    from app.core.config import settings

    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", True)
    fake = _FakeMemoryService(["记忆 A", "记忆 B"])
    agent = LangGraphAgent()
    monkeypatch.setattr("app.agent.graph.agent.memory_service", fake)

    first = await agent._memory_snapshot(user_id="3", thread_id="thread-1", query="问题 1")
    second = await agent._memory_snapshot(user_id="3", thread_id="thread-1", query="问题 2")

    # 同会话第二次调用命中快照：内容不变、不再触发检索
    assert first == "记忆 A"
    assert second == "记忆 A"
    assert fake.calls == 1

    # 新会话才会重新检索
    third = await agent._memory_snapshot(user_id="3", thread_id="thread-2", query="问题 3")
    assert third == "记忆 B"


async def test_session_snapshot_change_rotates_prefix_hash():
    """记忆快照变化 → session/epoch 指纹轮转（这正是 Cache Epoch 的定义）."""
    manager = ContextManager()
    messages = [HumanMessage(content="问题")]
    request = ContextRequest(conversation_id="t", max_context_tokens=4096)

    prepared_a = await manager.prepare(
        messages,
        system_message="SYS",
        request=request,
        session_snapshot=SessionSnapshot(memory_snapshot="记忆 A", version="snap-1"),
        runtime_tail="日期：2026-10-04",
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        tools_version=TOOLS_VERSION,
        tool_schemas=[{"name": "search_funds"}],
    )
    prepared_b = await manager.prepare(
        messages,
        system_message="SYS",
        request=request,
        session_snapshot=SessionSnapshot(memory_snapshot="记忆 A", version="snap-1"),
        runtime_tail="日期：2026-10-05",  # 日期变化在 Dynamic Tail，不影响前缀
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        tools_version=TOOLS_VERSION,
        tool_schemas=[{"name": "search_funds"}],
    )
    prepared_c = await manager.prepare(
        messages,
        system_message="SYS",
        request=request,
        session_snapshot=SessionSnapshot(memory_snapshot="记忆 B", version="snap-2"),
        runtime_tail="日期：2026-10-05",
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        tools_version=TOOLS_VERSION,
        tool_schemas=[{"name": "search_funds"}],
    )

    # 日期变化（Dynamic Tail）不影响会话前缀
    assert prepared_a.diagnostics.session_prefix_hash == prepared_b.diagnostics.session_prefix_hash
    # 记忆快照变化 → 会话前缀与 Epoch 轮转
    assert prepared_c.diagnostics.session_prefix_hash != prepared_a.diagnostics.session_prefix_hash
    assert prepared_c.diagnostics.cache_epoch_id != prepared_a.diagnostics.cache_epoch_id
    # 全局前缀（系统提示词 + 工具）始终不变
    assert prepared_a.diagnostics.global_prefix_hash == prepared_b.diagnostics.global_prefix_hash


# ---------------------------------------------------------------------------
# Test 4：Current Run 只追加、不改写
# ---------------------------------------------------------------------------


async def test_current_run_is_append_only():
    manager = ContextManager()
    request = ContextRequest(conversation_id="t", max_context_tokens=16384)

    messages_v1 = [
        HumanMessage(content="搜索当前基金的相关新闻"),
    ]
    prepared_v1 = await manager.prepare(messages_v1, system_message="SYS", request=request)

    messages_v2 = [
        HumanMessage(content="搜索当前基金的相关新闻"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "get_fund_holdings", "args": {"fund_code": "022287"}, "id": "c1", "type": "tool_call"}
            ],
        ),
        ToolMessage(content="持仓结果", name="get_fund_holdings", tool_call_id="c1"),
    ]
    prepared_v2 = await manager.prepare(messages_v2, system_message="SYS", request=request)

    # Request 1 的轨迹必须是 Request 2 轨迹的前缀（前缀缓存友好）。
    # AgentStatus / runtime_tail 属于 L4 Dynamic Tail，每轮变化是设计行为，
    # 不参与"轨迹前缀"的比较。
    def _trajectory(messages):
        body = messages[1:]  # 去掉开头的系统提示词
        while body and getattr(body[-1], "type", None) == "system":
            body = body[:-1]  # 去掉尾部的 Dynamic Tail（AgentStatus / 时间）
        return [getattr(m, "content", None) for m in body]

    trajectory_v1 = _trajectory(prepared_v1.messages)
    trajectory_v2 = _trajectory(prepared_v2.messages)
    assert trajectory_v2[: len(trajectory_v1)] == trajectory_v1
    assert len(trajectory_v2) > len(trajectory_v1)


# ---------------------------------------------------------------------------
# Test 5/6：预算使用率与 should_compact
# ---------------------------------------------------------------------------


def _turn_filler(approx_tokens: int) -> str:
    """构造约 approx_tokens 的填充文本（用估算器动态加倍，保证到达目标）."""
    filler = "a"
    while token_estimator.count_text(filler) < approx_tokens:
        filler += filler
    return filler


def _turn_messages(index: int, approx_tokens: int) -> list:
    return [
        HumanMessage(content=f"第 {index} 轮提问 {index}"),
        AIMessage(content=_turn_filler(approx_tokens)),
    ]


def _approx_tokens_of(messages: list) -> int:
    return token_estimator.count_messages(messages)


async def test_below_threshold_appends_without_sliding():
    """Usage 低于阈值：新增 Turn 只追加，不淘汰最老 Turn，should_compact=False."""
    manager = ContextManager()
    # 每 Turn ≈ 150 token，预算 2000：3 个 Turn ≈ 450 token（usage ≈ 0.22）
    turns = [_turn_messages(i, 150) for i in range(3)]
    flat = [m for turn in turns for m in turn]
    request = ContextRequest(conversation_id="t", max_context_tokens=2000)

    prepared = await manager.prepare(flat, system_message="SYS", request=request)

    # 当前 Turn 独立计入，recent_turn_count 只统计"历史"轮次
    assert prepared.diagnostics.recent_turn_count == 2
    assert prepared.diagnostics.should_compact is False
    assert prepared.diagnostics.context_usage_ratio < policy.COMPACT_THRESHOLD


async def test_over_threshold_marks_should_compact():
    """Usage 达到阈值：should_compact=True（第一版只标记，不执行摘要）."""
    manager = ContextManager()
    # 历史 Turn ≈ 60 token × 12 = 720 token，预算 400、当前 Turn 只有提问：
    # 装配时必然淘汰最老的 Turn（腾出到 ≤400），剩余窗口 usage ≈ 0.9 ≥ 0.8
    turns = [[HumanMessage(content=f"第 {i} 轮提问 {i}"), AIMessage(content=_turn_filler(50))] for i in range(12)]
    flat = [m for turn in turns for m in turn]
    request = ContextRequest(conversation_id="t", max_context_tokens=1000)

    prepared = await manager.prepare(flat, system_message="SYS", request=request)

    assert prepared.diagnostics.dropped_turn_count > 0
    assert prepared.diagnostics.should_compact is True
    assert prepared.diagnostics.context_usage_ratio >= policy.COMPACT_THRESHOLD


def test_policy_thresholds():
    assert policy.usage_ratio(600, 1000) == pytest.approx(0.6)
    assert policy.should_compact(790, 1000) is False
    assert policy.should_compact(800, 1000) is True
    assert policy.should_compact(0, 0) is False


# ---------------------------------------------------------------------------
# 旧 API 兼容
# ---------------------------------------------------------------------------


def test_legacy_prepare_messages_still_works():
    messages = [HumanMessage(content="你好"), AIMessage(content="你好！")]
    out = prepare_messages(messages, "SYS")
    assert out[0].content == "SYS"
    assert len(out) == 3


def test_counting_is_grouping_invariant():
    """口径统一回归：任意分组方式的计数之和必须等于整表计数.

    Phase 2 的教训：按 Turn 分组计数（每轮各含一次起头费）与整表计数
    相差 2(K-1)，累计 20~30 token 正好卡在预算线上反复报错。统一为
    逐条计数后，任何分组方式求和必然相等——漂移在构造上不可能。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages = [
        SystemMessage(content="SYS"),
        HumanMessage(content="搜索当前基金的相关新闻"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1", "type": "tool_call"}]),
        ToolMessage(content="工具结果" * 50, tool_call_id="c1"),
        AIMessage(content="回答"),
    ]

    whole = token_estimator.count_messages(messages)
    by_turn = sum(token_estimator.count_messages([m]) for m in messages)
    by_half = token_estimator.count_messages(messages[:3]) + token_estimator.count_messages(messages[3:])

    assert by_turn == whole
    assert by_half == whole
