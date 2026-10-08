# -*- coding: utf-8 -*-
"""水位线回归测试：压缩后旧 Turn 不复活、摘要覆盖与窗口严格对齐."""

from langchain_core.messages import HumanMessage, AIMessage

from tests.test_context_phase2 import _build_turns, _FakeSummaryManager, _prepare_with
from app.agent.context.manager import ContextManager
from app.agent.context.models import ContextRequest
from app.core.config import settings


async def test_watermark_prevents_revival(monkeypatch):
    """压缩后同会话再次请求：已压缩 Turn 不复活，摘要代为出场."""
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)

    # 第一次：按摘要输入预算压缩完整前缀，保留未覆盖原文。
    prepared_first = await _prepare_with(manager, messages, max_tokens=1000)
    assert prepared_first.diagnostics.current_user_present is True
    covered = sum(s.covered_turn_count for s in manager._summaries["phase2"])
    assert covered == len(fake.calls[0])
    assert 0 < covered <= 5

    # 第二次：同样的消息（模拟 checkpoint 重放）——已压缩 Turn 不得复活
    prepared_second = await _prepare_with(manager, messages, max_tokens=1000)
    contents = [str(getattr(m, "content", "")) for m in prepared_second.messages]
    assert all(f"第 {index} 轮提问" not in content for index in range(covered) for content in contents)
    # 摘要段在场，代表被压缩的内容
    assert any("此前对话摘要" in c for c in contents)

    # 覆盖对齐：水位线 + 未压缩区 == 全部 Turn（无盲区）
    total_segment_coverage = sum(s.covered_turn_count for s in manager._summaries["phase2"])
    # 此预算下全部未覆盖轮次可保留，摘要水位线与原文严格相邻。
    assert covered + prepared_second.diagnostics.recent_turn_count + 1 == 8
    assert total_segment_coverage == covered
    assert prepared_second.diagnostics.dropped_turn_count == 0
    assert [m.content for m in prepared_second.messages if m.type == "human"] == [
        f"第 {index} 轮提问 {index}" for index in range(covered, 8)
    ]


async def test_watermark_persists_across_requests(monkeypatch):
    """水位线跨请求持久：第二次请求不重置、也不重复压缩."""
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)
    await _prepare_with(manager, messages, max_tokens=1000)
    compressions_after_first = len(fake.calls)
    covered_after_first = manager._summaries["phase2"][-1].source_end

    await _prepare_with(manager, messages, max_tokens=1000)

    # 未新增未压缩内容 → 不重复压缩
    assert len(fake.calls) == compressions_after_first
    # 水位线保持不变（未重复压缩，未压缩区未增长到阈值）
    assert sum(s.covered_turn_count for s in manager._summaries["phase2"]) == covered_after_first


async def test_new_turns_append_without_re_compaction(monkeypatch):
    """压缩后新增小 Turn：append-only，不触发再次压缩（usage 低于阈值）."""
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    manager = ContextManager()
    fake = _FakeSummaryManager()
    manager.summary_manager = fake

    messages = _build_turns(8, body_tokens=190)
    await _prepare_with(manager, messages, max_tokens=1000)
    compressions_before = len(fake.calls)

    grown = [*messages, HumanMessage(content="新的一轮提问"), AIMessage(content="新的一轮回答")]
    prepared = await manager.prepare(
        grown,
        system_message="SYS",
        request=ContextRequest(conversation_id="phase2", max_context_tokens=1000),
    )

    assert len(fake.calls) == compressions_before  # 未再压缩
    assert any(getattr(m, "content", None) == "新的一轮提问" for m in prepared.messages)
