"""真实摘要算法的连续压缩、来源、失败与并发回归；仅替换外部模型 IO."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, START, MessagesState, StateGraph

from app.agent.context import state_store
from app.agent.context.budget import token_estimator
from app.agent.context.cache_policy import cache_policy
from app.agent.context.manager import ContextManager
from app.agent.context.models import ContextInvariantError, ContextRequest
from app.agent.context.summary import ConversationSummaryManager, turn_hash
from app.core.config import settings
from app.services.llm.registry import _build_chat_model


def messages(count: int) -> list:
    return [
        message
        for index in range(count)
        for message in (
            HumanMessage(content=f"question {index}", id=f"human-{index}"),
            AIMessage(content="alpha beta gamma delta " * 80 + f"fact-{index}", id=f"ai-{index}"),
        )
    ]


async def summary_text(_messages):
    return "用户讨论了基金持仓，要求保留约束与结论。"


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", True)
    monkeypatch.setattr(settings, "AGENT_STATUS_ENABLED", False)
    monkeypatch.setattr(settings, "SUMMARY_SEGMENT_MERGE_COUNT", 100)
    monkeypatch.setattr(settings, "SUMMARY_REGION_MAX_RATIO", 0.9)
    result = ContextManager()
    result.summary_manager = ConversationSummaryManager(summary_text)
    return result


async def prepare(manager, history, budget=1800, **kwargs):
    return await manager.prepare(
        history,
        system_message="SYS",
        request=ContextRequest(conversation_id="v2", max_context_tokens=budget),
        **kwargs,
    )


async def test_consecutive_compactions_and_restart_have_exact_watermark(manager):
    prior_end = 0
    prior_version = 0
    for count in (8, 12, 16):
        prepared = await prepare(manager, messages(count))
        segments = prepared.envelope.conversation_summary
        state_store.validate_segments(segments)
        assert segments[-1].source_end > prior_end
        assert sum(segment.covered_turn_count for segment in segments) == segments[-1].source_end
        assert segments[-1].version > prior_version
        assert segments[-1].source_end <= count - 3  # 当前轮和最近两轮不进入摘要
        turns = manager._group_messages_into_turns(messages(count))
        assert [source for segment in segments for source in segment.source_turn_hashes] == [
            turn_hash(turn) for turn in turns[: segments[-1].source_end]
        ]
        assert prepared.messages[0].content == "SYS"
        assert prepared.diagnostics.total_tokens <= 1800
        prior_end, prior_version = segments[-1].source_end, segments[-1].version
    # 新实例恢复完全相同的段；提高预算避免再次触发。
    restarted = ContextManager()
    restarted.summary_manager = ConversationSummaryManager(summary_text)
    restored = await prepare(restarted, messages(16), budget=10000)
    assert restored.envelope.conversation_summary == segments
    assert restarted._epochs["v2"].sequence == manager._epochs["v2"].sequence


async def test_merge_only_oldest_half_and_preserves_sources(manager, monkeypatch):
    for count in (8, 12, 16, 20):
        await prepare(manager, messages(count))
    original = manager._summaries["v2"]
    assert len(original) == 4
    monkeypatch.setattr(settings, "SUMMARY_MERGE_FRACTION", 0.5)
    merged, calls = await manager._merge_oldest_pairwise(original, 5000, 300)
    assert calls == 1
    assert merged[1:] == original[2:]
    assert merged[0].version > max(segment.version for segment in original)
    state_store.validate_segments(merged)
    assert sum(segment.covered_turn_count for segment in merged) == sum(
        segment.covered_turn_count for segment in original
    )
    assert merged[0].source_turn_hashes == original[0].source_turn_hashes + original[1].source_turn_hashes


async def test_merge_failure_preserves_original_segments(manager, monkeypatch, _fake_context_state_store):
    await prepare(manager, messages(8))
    await prepare(manager, messages(12))
    old = list(manager._summaries["v2"])
    old_epoch = manager._epochs["v2"].sequence
    old_payload = dict(_fake_context_state_store["v2"])
    monkeypatch.setattr(settings, "BATCH_COMPACTION_ENABLED", False)
    monkeypatch.setattr(settings, "SUMMARY_SEGMENT_MERGE_COUNT", 1)

    async def failed(_messages):
        raise RuntimeError("merge unavailable")

    manager.summary_manager = ConversationSummaryManager(failed)
    prepared = await prepare(manager, messages(12), budget=10000)
    assert prepared.diagnostics.compaction_failed
    assert prepared.envelope.conversation_summary == old
    assert manager._epochs["v2"].sequence == old_epoch
    assert _fake_context_state_store["v2"] == old_payload


@pytest.mark.parametrize("output", ["", "  \n", "overflow " * 1000])
async def test_invalid_summary_does_not_advance_watermark(manager, output, _fake_context_state_store):
    async def invalid(_messages):
        return output

    manager.summary_manager = ConversationSummaryManager(invalid)
    prepared = await prepare(manager, messages(8))
    assert prepared.diagnostics.compaction_failed
    assert prepared.envelope.conversation_summary == []
    assert "v2" not in _fake_context_state_store
    assert "v2" not in manager._epochs


@pytest.mark.parametrize(
    "response",
    [
        AIMessage(content="", tool_calls=[{"name": "tool", "args": {}, "id": "call"}]),
        AIMessage(content="partial", response_metadata={"finish_reason": "length"}),
        AIMessage(content="refused", additional_kwargs={"refusal": "blocked"}),
        AIMessage(content=[{"type": "reasoning", "reasoning": "hidden"}]),
    ],
)
async def test_default_executor_rejects_unusable_responses(response):
    executor = ConversationSummaryManager()
    observed = {}

    async def call(_messages, **kwargs):
        observed.update(kwargs)
        return response

    executor.llm_call = call
    with pytest.raises(ValueError):
        await executor._summarize([HumanMessage(content="summarize")], 100)
    assert observed == {"max_tokens": 100, "tags": ["nostream", "context_summary"]}


async def test_complete_message_tail_and_tool_arguments_reach_summarizer():
    observed = []

    async def capture(inputs):
        observed.extend(inputs)
        return "用户要求保留关键限制。"

    executor = ConversationSummaryManager(capture)
    history = [
        HumanMessage(content="内容" * 400 + "末尾关键约束", id="u"),
        AIMessage(content="", tool_calls=[{"name": "fund", "args": {"code": "123456"}, "id": "c"}]),
        ToolMessage(content="结果" * 300 + "末尾结论", name="fund", tool_call_id="c"),
        AIMessage(content="确认"),
    ]
    turns = ContextManager._group_messages_into_turns(history)
    result = await executor.compact(
        turns=turns, source_start=0, version=1, input_token_limit=5000, output_token_limit=100
    )
    assert "末尾关键约束" in observed[-1].content
    assert "末尾结论" in observed[-1].content
    assert "123456" in observed[-1].content
    assert result.summary.covered_from_turn_id == result.summary.covered_until_turn_id == "u"


async def test_oversized_single_turn_does_not_call_llm():
    called = False

    async def capture(inputs):
        nonlocal called
        called = True
        return "summary"

    executor = ConversationSummaryManager(capture)
    turns = ContextManager._group_messages_into_turns(messages(1))
    with pytest.raises(ValueError):
        await executor.compact(turns=turns, source_start=0, version=1, input_token_limit=50, output_token_limit=100)
    assert not called


async def test_clear_during_summary_prevents_old_state_resurrection(manager, _fake_context_state_store):
    started, resume = asyncio.Event(), asyncio.Event()

    async def paused(_messages):
        started.set()
        await resume.wait()
        return "旧会话摘要"

    manager.summary_manager = ConversationSummaryManager(paused)
    pending = asyncio.create_task(prepare(manager, messages(8)))
    await started.wait()
    # 模拟与 checkpoint 清空同一事务提交的持久化修订号递增。
    _fake_context_state_store["v2"] = {**state_store.serialize_state([], 1), "_revision": 1}
    manager.forget_thread("v2")
    resume.set()
    with pytest.raises(ContextInvariantError, match="会话在压缩期间已变化"):
        await pending
    assert state_store.parse_state(_fake_context_state_store["v2"]) == ([], 1)
    assert "v2" not in manager._summaries
    assert "v2" not in manager._epochs


async def test_two_workers_cannot_overwrite_each_other(manager):
    started, resume = asyncio.Event(), asyncio.Event()

    async def paused(_messages):
        started.set()
        await resume.wait()
        return "worker one summary"

    manager.summary_manager = ConversationSummaryManager(paused)
    pending = asyncio.create_task(prepare(manager, messages(8)))
    await started.wait()
    other = ContextManager()
    other.summary_manager = ConversationSummaryManager(summary_text)
    committed = await prepare(other, messages(8))
    resume.set()
    with pytest.raises(ContextInvariantError):
        await pending
    loaded = await state_store.load_context_state("v2")
    assert loaded.segments == committed.envelope.conversation_summary


async def test_same_worker_serializes_summary_requests(manager):
    calls = 0

    async def count(_messages):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "summary"

    manager.summary_manager = ConversationSummaryManager(count)
    first, second = await asyncio.gather(prepare(manager, messages(8)), prepare(manager, messages(8), budget=10000))
    assert calls == 1
    assert first.envelope.conversation_summary == second.envelope.conversation_summary


async def test_other_worker_clear_invalidates_cached_summaries(manager, _fake_context_state_store):
    await prepare(manager, messages(8))
    old_revision = _fake_context_state_store["v2"]["_revision"]
    _fake_context_state_store["v2"] = {**state_store.serialize_state([], 1), "_revision": old_revision + 1}
    prepared = await prepare(manager, messages(1), budget=10000)
    assert prepared.envelope.conversation_summary == []
    assert "v2" not in manager._summaries


async def test_legacy_v1_counts_are_ignored_and_rebuilt(manager, _fake_context_state_store):
    _fake_context_state_store["v2"] = {
        "version": 1,
        "segments": [{"content": "overlap", "covered_turn_count": 999}],
        "epoch_sequence": 20,
    }
    prepared = await prepare(manager, messages(8))
    assert _fake_context_state_store["v2"]["version"] == 2
    assert prepared.envelope.conversation_summary[0].source_start == 0
    assert prepared.envelope.conversation_summary[0].covered_turn_count < 8


async def test_changed_checkpoint_never_uses_stale_summary(manager):
    await prepare(manager, messages(8))
    replaced = messages(8)
    replaced[0].content = "replacement history"
    prepared = await prepare(manager, replaced, budget=10000)
    assert prepared.envelope.conversation_summary == []
    assert replaced[0] in prepared.messages


async def test_budget_includes_summaries_tail_schemas_and_tool_arguments(manager):
    await prepare(manager, messages(8))
    schema = [{"type": "function", "function": {"name": "fund", "description": "schema " * 90}}]
    prepared = await prepare(manager, messages(8), budget=10000, runtime_tail="time " * 100, tool_schemas=schema)
    assert prepared.diagnostics.total_tokens == (
        token_estimator.count_messages(prepared.messages) + token_estimator.count_tool_schemas(schema)
    )
    plain = AIMessage(content="")
    call = AIMessage(content="", tool_calls=[{"name": "fund", "args": {"query": "args " * 90}, "id": "c"}])
    assert token_estimator.count_message(call) > token_estimator.count_message(plain) + 80


async def test_summary_change_changes_epoch_fingerprint(manager):
    first = await prepare(manager, messages(8))
    second = await prepare(manager, messages(12))
    assert first.diagnostics.epoch_prefix_hash != second.diagnostics.epoch_prefix_hash
    assert first.diagnostics.global_prefix_hash == second.diagnostics.global_prefix_hash


async def test_compaction_threshold_counts_tool_schemas_and_dynamic_tail(manager):
    history = [
        message
        for index in range(5)
        for message in (HumanMessage(content=f"short question {index}"), AIMessage(content="answer " * 10))
    ]
    first = await prepare(manager, history, budget=1000)
    assert first.envelope.conversation_summary == []
    schema = [{"description": "schema " * 650}]
    second = await prepare(manager, history, budget=1000, tool_schemas=schema, runtime_tail="time " * 150)
    assert second.envelope.conversation_summary
    assert second.diagnostics.total_tokens <= 1000


async def test_failed_state_load_retries_without_publishing_unverified_watermark(manager, monkeypatch):
    original_load = state_store.load_context_state

    async def failed(_thread):
        raise OSError("temporary read failure")

    monkeypatch.setattr(state_store, "load_context_state", failed)
    first = await prepare(manager, messages(8))
    assert first.envelope.conversation_summary == []
    assert "v2" not in manager._state_loaded
    monkeypatch.setattr(state_store, "load_context_state", original_load)
    second = await prepare(manager, messages(8))
    assert second.envelope.conversation_summary


async def test_internal_summary_tokens_are_excluded_from_real_graph_stream():
    internal = FakeListChatModel(responses=["内部压缩内容，不应发给用户"])
    answer = FakeListChatModel(responses=["这是正式回答"])
    executor = ConversationSummaryManager()

    async def call(inputs, **kwargs):
        return await internal.with_config(tags=kwargs["tags"]).ainvoke(inputs)

    executor.llm_call = call

    async def chat(state: MessagesState):
        summary = await executor._summarize([HumanMessage(content="summarize")], 100)
        assert summary == "内部压缩内容，不应发给用户"
        return {"messages": [await answer.ainvoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("chat", chat)
    builder.add_edge(START, "chat")
    builder.add_edge("chat", END)
    graph = builder.compile()
    streamed = [
        token.content
        async for token, _ in graph.astream({"messages": [HumanMessage(content="question")]}, stream_mode="messages")
    ]
    assert "".join(streamed) == "这是正式回答"


def test_summary_tags_bind_to_model_without_becoming_provider_parameters():
    model = _build_chat_model(
        "fixture-model",
        "fixture-key",  # pragma: allowlist secret -- inert fixture
        "https://fixture.example/v1",  # pragma: allowlist secret -- inert fixture
        max_tokens=100,
        tags=["nostream", "context_summary"],
    )
    assert model.tags == ["nostream", "context_summary"]
    assert "tags" not in model.model_kwargs


def test_v2_rejects_overlapping_or_tampered_sources():
    hashes = ["source"]
    segment = {
        "content": "facts",
        "version": 1,
        "source_start": 0,
        "source_end": 1,
        "covered_turn_count": 1,
        "source_turn_hashes": hashes,
        "source_hash": cache_policy.fingerprint(hashes),
    }
    valid = {"version": 2, "segments": [segment], "epoch_sequence": 2}
    assert state_store.parse_state(valid) is not None
    assert state_store.parse_state({**valid, "segments": [segment, {**segment, "version": 2}]}) is None
    assert state_store.parse_state({**valid, "segments": [{**segment, "covered_turn_count": 3}]}) is None
    assert state_store.parse_state({**valid, "segments": [{**segment, "source_hash": "tampered"}]}) is None
