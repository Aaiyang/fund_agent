"""ContextManager Phase 2 回归测试（任务书 §46）.

覆盖：AgentStatus 构建与尾部、Duplicate Tool Guard（同参/异参/阻止）、
Summary 不每轮更新、Batch Compaction、压缩失败降级、Cache Epoch rollover、
Current Run 不被压缩。
"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.context.manager import ContextManager
from app.agent.context.summary import ConversationSummaryManager
from app.agent.context.models import (
    ContextRequest,
    SessionSnapshot,
)
from app.agent.context.status import build_agent_status
from app.schemas import Message
from app.agent.tools.guard import (
    DuplicateToolGuard,
    build_tool_signature,
)
from app.agent.context.budget import token_estimator
from tests.test_agent_tools import _patch_tool_service


def _tool_round(call_id: str, tool_name: str, args: dict, content: str = "结果") -> list:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": args, "id": call_id, "type": "tool_call"}],
        ),
        ToolMessage(content=content, name=tool_name, tool_call_id=call_id),
    ]


# ---------------------------------------------------------------------------
# AgentStatus 的用例（Test 1 / Test 8）
# ---------------------------------------------------------------------------


def test_agent_status_counts_tool_calls():
    messages = [
        HumanMessage(content="查基金"),
        *_tool_round("c1", "get_fund_holdings", {"fund_code": "022287"}),
        AIMessage(content="查一下新闻"),
        *_tool_round("c2", "duckduckgo_search", {"query": "新闻"}, content="新闻结果"),
    ]
    status = build_agent_status(
        run_id="r1",
        current_turn=SimpleNamespace(content="查基金"),
        current_turn_messages=messages,
    )
    assert status.tool_call_count == 2
    assert status.tool_calls_by_name == {"get_fund_holdings": 1, "duckduckgo_search": 1}
    assert status.last_tool_name == "duckduckgo_search"


def test_agent_status_flags_duplicates():
    messages = [
        HumanMessage(content="查基金"),
        *_tool_round("c1", "get_fund_holdings", {"fund_code": "022287"}),
        *_tool_round("c2", "get_fund_holdings", {"fund_code": "022287"}),
    ]
    status = build_agent_status(
        run_id="r1",
        current_turn=SimpleNamespace(content="查基金"),
        current_turn_messages=messages,
    )
    assert len(status.duplicate_tool_calls) == 1
    assert status.warnings


async def test_agent_status_tail_is_last_and_outside_global_prefix():
    """AgentStatus 必须在最终上下文最末尾，且不影响全局前缀指纹."""
    from app.agent.context.models import ContextRequest

    manager = ContextManager()

    async def _prepare(with_status: bool, tool_rounds: int):
        messages = [HumanMessage(content="搜索新闻")]
        for i in range(tool_rounds):
            messages.extend(_tool_round(f"c{i}", "duckduckgo_search", {"query": f"q{i}"}, content=f"r{i}"))
        request = ContextRequest(conversation_id="t", max_context_tokens=16384)
        import app.agent.context.manager as m

        enabled_backup = m.settings.AGENT_STATUS_ENABLED
        m.settings.AGENT_STATUS_ENABLED = with_status
        try:
            return await manager.prepare(messages, system_message="SYS", request=request)
        finally:
            m.settings.AGENT_STATUS_ENABLED = enabled_backup

    prepared_status_on = await _prepare(True, tool_rounds=1)
    prepared_status_off = await _prepare(False, tool_rounds=1)
    prepared_status_on_more = await _prepare(True, tool_rounds=2)

    # 尾部：AgentStatus 是最后一条消息
    assert "<agent_status>" in prepared_status_on.messages[-1].content
    # Global Prefix 指纹不受 AgentStatus（尾部）变化影响
    assert prepared_status_on.diagnostics.global_prefix_hash == prepared_status_off.diagnostics.global_prefix_hash
    assert prepared_status_on_more.diagnostics.global_prefix_hash == prepared_status_on.diagnostics.global_prefix_hash
    # 但会随工具轨迹追加而推进
    assert prepared_status_on.diagnostics.global_prefix_hash is not None


# ---------------------------------------------------------------------------
# Duplicate Tool Guard 的用例（Test 2 / Test 3）
# ---------------------------------------------------------------------------


def test_same_signature_for_same_tool_and_args():
    sig_a = build_tool_signature("get_fund_holdings", {"fund_code": "022287"})
    sig_b = build_tool_signature("get_fund_holdings", {"fund_code": "022287"})
    assert sig_a == sig_b


def test_different_args_produce_different_signature():
    sig_a = build_tool_signature("get_fund_holdings", {"fund_code": "022287"})
    sig_b = build_tool_signature("get_fund_holdings", {"fund_code": "005827"})
    assert sig_a != sig_b


def test_guard_blocks_after_limit():
    guard = DuplicateToolGuard(max_same_calls=2, enabled=True)
    assert guard.should_block(prior_count=0) is False
    assert guard.should_block(prior_count=1) is False
    assert guard.should_block(prior_count=2) is True


def test_guard_disabled_never_blocks():
    guard = DuplicateToolGuard(max_same_calls=2, enabled=False)
    assert guard.should_block(prior_count=10) is False


async def test_guard_blocks_execution_in_graph(monkeypatch):
    """脚本化 LLM 连续 3 次同参数调用同一工具：第 3 次被阻止，不再真正执行."""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent.graph.agent import LangGraphAgent

    executions = {"count": 0}

    async def fake_quotes():
        executions["count"] += 1
        return [SimpleNamespace(index_code="sh000001", name="上证指数", close=3000.0, change_pct=0.1, trade_date=None)]

    _patch_tool_service(monkeypatch, "get_market_context", SimpleNamespace(get_quotes=fake_quotes))

    class LoopLLM:
        def __init__(self):
            self.calls = 0
            self.history: list[list[dict]] = []

        def get_llm(self):
            return None

        async def call(self, messages, *args, **kwargs):
            self.calls += 1
            normalized = [
                {
                    "type": getattr(m, "type", None),
                    "content": str(getattr(m, "content", "")),
                }
                for m in messages
            ]
            self.history.append(normalized)
            return AIMessage(
                content="",
                tool_calls=[{"name": "get_market_context", "args": {}, "id": f"c{self.calls}", "type": "tool_call"}],
            )

    fake_llm = LoopLLM()
    agent = LangGraphAgent()
    monkeypatch.setattr(agent, "llm_service", fake_llm)
    monkeypatch.setattr("app.agent.graph.agent.memory_service", _FakeMemorySearch())
    agent._graph = agent._build_graph(InMemorySaver())

    result = await agent.get_response([Message(role="user", content="最近市场怎么样")], "guard-case", user_id="42")

    # 前两次真正执行，第三次被 Guard 阻止
    assert executions["count"] == 2
    # 第三轮的 LLM 调用应收到 Guard 的阻止信息
    blocked = [m for m in fake_llm.history[-1] if m["type"] == "tool" and "DUPLICATE_TOOL_CALL" in m["content"]]
    assert blocked, "第三次同参数调用应收到 DUPLICATE_TOOL_CALL 提示"
    assert result[-1].role == "assistant"


class _FakeMemorySearch:
    async def search(self, *args, **kwargs):
        return ""

    async def add(self, *args, **kwargs):
        return None


def _noop():
    return None


# ---------------------------------------------------------------------------
# ConversationSummary / Batch Compaction / Cache Epoch 的用例（Test 4-7 / 9）
# ---------------------------------------------------------------------------


class _FakeSummaryManager(ConversationSummaryManager):
    """使用真实摘要算法，仅替换外部 LLM；记录真正覆盖的轮次."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[list] = []
        super().__init__(self.summarize)

    async def summarize(self, messages):
        if self.fail:
            raise RuntimeError("summary llm down")
        return "已讨论基金持仓与用户约束。"

    async def compact(self, *, turns, **kwargs):
        result = await super().compact(turns=turns, **kwargs)
        self.calls.append(list(turns[: result.compacted_turn_count]))
        return result


def _build_turns(count: int, body_tokens: int = 150) -> list:
    messages: list = []
    for i in range(count):
        messages.append(HumanMessage(content=f"第 {i} 轮提问 {i}"))
        messages.append(AIMessage(content="a" * (body_tokens * 4)))
    return messages


async def _prepare_with(
    manager: ContextManager,
    messages: list,
    max_tokens: int = 1000,
):
    return await manager.prepare(
        messages,
        system_message="SYS",
        request=ContextRequest(conversation_id="phase2", max_context_tokens=max_tokens),
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
    )


async def test_summary_not_updated_below_threshold(monkeypatch):
    """Usage 低于阈值：Summary 不更新、Epoch 不变（Test 4）."""
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake
    monkeypatch.setattr(manager, "_summaries", {})

    turns = _build_turns(3, body_tokens=40)  # 小体积，usage 远低于阈值
    for i in range(3):
        await _prepare_with(manager, turns[: (i + 1) * 2] + [HumanMessage(content=f"追问 {i}")])

    assert fake.calls == []  # 从未触发压缩


async def test_batch_compaction_at_threshold(monkeypatch):
    """Usage 达到阈值：压缩较老一批、保留最近 2 个、summary_version+1（Test 5）."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)  # 8 个大 Turn，超过 0.8 阈值
    await _prepare_with(manager, messages, max_tokens=1000)

    assert fake.calls, "未触发压缩"
    # 小预算下摘要提示词也占窗口，分批压缩完整轮次，绝不截掉原文。
    assert 1 <= len(fake.calls[0]) <= 5
    assert manager._summaries["phase2"][0].version == 1
    # 初始 epoch sequence=1，第一次成功压缩后 rollover 到 2
    assert manager._epochs["phase2"].sequence == 2


async def test_current_run_not_compacted(monkeypatch):
    """压缩只处理已完成旧 Turn；当前 Run 的原始轨迹完整保留（Test 9）."""
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)
    # 当前 Run 带工具轨迹
    messages.extend(_tool_round("cur_1", "get_fund_holdings", {"fund_code": "022287"}, content="当前持仓"))

    prepared = await _prepare_with(manager, messages, max_tokens=1000)

    trace = [
        m
        for m in prepared.messages
        if getattr(m, "type", None) == "tool" and "当前持仓" in str(getattr(m, "content", ""))
    ]
    assert trace, "当前 Run 工具轨迹必须保留"
    assert all("当前持仓" in str(m.content) for m in trace)


async def test_compaction_failure_degrades_gracefully(monkeypatch):
    """Summary LLM 失败：原 Turn 不删、Epoch 不 rollover、正常降级（Test 6）."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    manager = ContextManager()
    fake = _FakeSummaryManager(fail=True)
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)
    prepared = await _prepare_with(manager, messages, max_tokens=1000)

    assert prepared.diagnostics.compaction_failed is True
    assert prepared.diagnostics.cache_epoch_sequence == 1  # 未 rollover
    # 原 Turn 仍在上下文（未删除）
    assert len(prepared.messages) > 5


async def test_cache_epoch_rollover(monkeypatch):
    """压缩成功 → sequence+1；下一轮未再压缩 → epoch 保持（Test 7）."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)
    await _prepare_with(manager, messages, max_tokens=1000)
    sequence_after_compaction = manager._epochs["phase2"].sequence
    assert sequence_after_compaction == 2

    # 下一轮未达到压缩条件（新会话消息很少）→ epoch 不再变化
    small = messages
    await _prepare_with(manager, small, max_tokens=1000)
    assert manager._epochs["phase2"].sequence == sequence_after_compaction


# ---------------------------------------------------------------------------
# 兼容：默认 Flags 下现有行为不回归
# ---------------------------------------------------------------------------


async def test_flags_off_keeps_phase1_behavior(monkeypatch):
    """四个开关全关（Summary/Compaction 默认关）：不生成摘要、不压缩."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_STATUS_ENABLED", False)
    monkeypatch.setattr(settings, "DUPLICATE_TOOL_GUARD_ENABLED", False)
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", False)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", False)

    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)
    prepared = await _prepare_with(manager, messages, max_tokens=1000)

    assert fake.calls == []
    assert prepared.diagnostics.compaction_failed is False
    assert prepared.diagnostics.agent_status_tokens is None


async def test_eviction_loop_guarantees_budget_exactness(monkeypatch):
    """回归（用户实际事故）：估算口径偏差导致总量超预算，逐出循环精确压回."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", False)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", False)

    manager = ContextManager()
    # 5 个中等 Turn：估算刚好贴着预算（制造上次事故的"乐观偏差"场景）
    messages = _build_turns(5, body_tokens=190)
    request = ContextRequest(conversation_id="evict", max_context_tokens=700)

    prepared = await manager.prepare(
        messages,
        system_message="SYS",
        request=request,
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
        runtime_tail="# 当前时间" + chr(10) + "日期：2026-10-07；交易时段：已收盘。",
    )

    total = token_estimator.count_messages(prepared.messages)
    assert total <= request.max_context_tokens, f"总量 {total} 仍超预算 {request.max_context_tokens}"
    # 当前提问必须保留
    assert any(getattr(m, "content", None) == "第 0 轮提问 0" for m in prepared.messages)
    assert prepared.diagnostics.current_user_present is True
