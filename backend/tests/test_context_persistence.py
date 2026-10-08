"""摘要持久化回归测试（session.context_state + ContextManager 接线）.

覆盖：载荷序列化往返（datetime 安全）、损坏载荷容错、进程重启后
摘要段与水位线恢复、落盘失败降级、会话删除后的进程内状态清理。
数据库 IO 由 conftest 的内存版仓库替身承载，序列化/解析走真实实现。
"""

import uuid
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.context import state_store
from app.agent.context.cache_policy import cache_policy
from app.agent.context.manager import ContextManager
from app.agent.context.summary import ConversationSummaryManager
from app.agent.context.models import (
    ConversationSummary,
    ContextRequest,
    SessionSnapshot,
)
from app.core.config import settings


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


def _build_turns(count: int, body_tokens: int = 190) -> list:
    messages: list = []
    for i in range(count):
        messages.append(HumanMessage(content=f"第 {i} 轮提问 {i}"))
        messages.append(AIMessage(content="a" * (body_tokens * 4)))
    return messages


def _summary(version: int = 1) -> ConversationSummary:
    return ConversationSummary(
        content="此前讨论了基金 A 的持仓结构",
        version=version,
        covered_turn_count=5,
        source_start=(version - 1) * 5,
        source_end=version * 5,
        source_turn_hashes=["fixture"] * 5,
        source_hash=cache_policy.fingerprint(["fixture"] * 5),
        covered_until_turn_id="turn-5",
        created_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC).replace(tzinfo=None),
    )


def test_state_store_roundtrip():
    """Serialize → parse 字段逐一还原（含 datetime 序列化）."""
    payload = state_store.serialize_state([_summary(1), _summary(2)], 3)

    state = state_store.parse_state(payload)
    assert state is not None
    segments, sequence = state
    assert sequence == 3
    assert [segment.version for segment in segments] == [1, 2]
    assert segments[0].covered_turn_count == 5
    assert segments[0].created_at == datetime(2026, 10, 7, 12, 0)


def test_state_store_corrupt_or_missing_payload():
    """载荷缺失、版本不识别、字段损坏一律视为无状态（None），不抛异常."""
    assert state_store.parse_state(None) is None
    assert state_store.parse_state("not a dict") is None  # pyright: ignore[reportArgumentType]
    assert state_store.parse_state({"version": 999, "segments": [], "epoch_sequence": 1}) is None
    assert state_store.parse_state({"version": 1, "segments": "nope", "epoch_sequence": 1}) is None
    assert state_store.parse_state({"version": 1, "segments": [], "epoch_sequence": 0}) is None
    assert state_store.parse_state({"version": 1, "segments": [{"bogus": 1}], "epoch_sequence": 1}) is None


async def test_restart_restores_summary_and_watermark(_fake_context_state_store, monkeypatch):
    """进程重启（新 manager 实例）后：摘要段恢复、水位线不回退、不重复压缩."""
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)

    thread_key = f"persist-{uuid.uuid4().hex[:8]}"
    messages = _build_turns(8)

    # ---- 第一次"进程"：触发压缩并落盘 ----
    manager1 = ContextManager()
    fake1 = _FakeSummaryManager()
    manager1.summary_manager = fake1
    prepared1 = await manager1.prepare(
        messages,
        system_message="SYS",
        request=ContextRequest(conversation_id=thread_key, max_context_tokens=1000),
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
    )
    assert fake1.calls, "压缩未触发"
    assert thread_key in _fake_context_state_store
    assert manager1._epochs[thread_key].sequence == 2

    # ---- 第二次"进程"：全新实例（内存为空），从会话行恢复 ----
    manager2 = ContextManager()
    assert manager2._summaries == {}
    fake2 = _FakeSummaryManager()
    manager2.summary_manager = fake2
    prepared2 = await manager2.prepare(
        messages,
        system_message="SYS",
        request=ContextRequest(conversation_id=thread_key, max_context_tokens=1000),
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
    )

    restored_segments = manager2._summaries[thread_key]
    assert [segment.version for segment in restored_segments] == [1]
    assert restored_segments[0].covered_turn_count == fake1.calls[0].__len__()
    assert manager2._epochs[thread_key].sequence == 2
    # 水位线恢复：两个进程看到相同的窗口形状，且不再触发压缩
    assert prepared2.diagnostics.recent_turn_count == prepared1.diagnostics.recent_turn_count
    assert prepared2.diagnostics.summary_version == prepared1.diagnostics.summary_version == 1
    assert fake2.calls == []


async def test_persist_failure_degrades_gracefully(monkeypatch):
    """落盘失败不推进水位线，保留预算内的原始历史."""

    async def _broken_save(*args, **kwargs):
        raise OSError("db write failed")

    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    monkeypatch.setattr(state_store, "save_context_state", _broken_save)

    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake
    prepared = await manager.prepare(
        _build_turns(8),
        system_message="SYS",
        request=ContextRequest(conversation_id="persist-fail", max_context_tokens=1000),
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
    )

    assert fake.calls, "压缩不应受落盘失败影响"
    assert prepared.diagnostics.compaction_failed is True
    assert prepared.diagnostics.summary_version is None
    assert "persist-fail" not in manager._summaries
    assert "persist-fail" not in manager._epochs


async def test_forget_thread_clears_inprocess_state(_fake_context_state_store, monkeypatch):
    """会话删除后：进程内摘要清空；存储也没了时不会再恢复."""
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)

    thread_key = f"forget-{uuid.uuid4().hex[:8]}"
    manager = ContextManager()
    manager.summary_manager = _FakeSummaryManager()
    await manager.prepare(
        _build_turns(8),
        system_message="SYS",
        request=ContextRequest(conversation_id=thread_key, max_context_tokens=1000),
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
    )
    assert manager._summaries[thread_key]

    manager.forget_thread(thread_key)
    assert thread_key not in manager._summaries
    assert thread_key not in manager._epochs
    assert thread_key not in manager._state_loaded

    # 模拟会话行已删（context_state 随行消失）：再次 prepare 不复活旧摘要。
    # 用小会话（低于压缩阈值），排除"新一轮合法压缩"的干扰。
    _fake_context_state_store.pop(thread_key, None)
    await manager.prepare(
        _build_turns(2, body_tokens=10),
        system_message="SYS",
        request=ContextRequest(conversation_id=thread_key, max_context_tokens=1000),
        session_snapshot=SessionSnapshot(memory_snapshot="记忆"),
    )
    assert thread_key not in manager._summaries
