"""Budget regressions for batched tool calls: a call and all results are atomic."""

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.context.budget import hard_limit_tool_trace, token_estimator
from app.agent.context.manager import ContextManager, _fit_budget
from app.agent.context.models import ContextInvariantError, ContextRequest
from app.agent.graph import LangGraphAgent
from app.core.config import settings
from app.schemas import Message


def batch(prefix: str, count: int, size: int = 120) -> list:
    calls = [{"id": f"{prefix}_{i}", "name": f"tool_{i}", "args": {}} for i in range(count)]
    return [
        AIMessage(content="", tool_calls=calls),
        *[
            ToolMessage(content=f"{prefix}_{i}:" + "行情数据" * size, tool_call_id=call["id"], name=call["name"])
            for i, call in enumerate(calls)
        ],
    ]


def assert_paired(messages: list) -> None:
    pending = set()
    for message in messages:
        if isinstance(message, AIMessage):
            assert not pending
            pending.update(call["id"] for call in message.tool_calls)
        elif isinstance(message, ToolMessage):
            assert message.tool_call_id in pending
            pending.remove(message.tool_call_id)
    assert not pending


@pytest.mark.parametrize("count", [1, 2, 3, 4, 8])
async def test_over_budget_preserves_entire_latest_batch(count: int):
    human = HumanMessage(content="分析我的基金")
    latest = batch("latest", count)
    # Result ordering can differ from call ordering.
    latest[1:] = reversed(latest[1:])
    messages = [human, *batch("old", 3, 400), *latest]
    originals = [message.model_dump() for message in messages]
    budget = token_estimator.count_messages([human, *latest]) + 300
    prepared = await ContextManager().prepare(
        messages, system_message="SYS", request=ContextRequest(max_context_tokens=budget)
    )
    assert_paired(prepared.messages)
    assert prepared.envelope.current_turn_messages == [human, *latest]
    assert prepared.diagnostics.total_tokens <= budget
    assert [message.model_dump() for message in messages] == originals


async def test_latest_batch_cannot_fit_returns_budget_error():
    messages = [HumanMessage(content="分析基金"), *batch("latest", 4, 250)]
    with pytest.raises(ContextInvariantError) as caught:
        await ContextManager().prepare(messages, system_message="SYS", request=ContextRequest(max_context_tokens=400))
    assert caught.value.code == "CONTEXT_BUDGET_EXCEEDED"


async def test_orphan_tool_result_is_still_rejected():
    # 没有对应 AI ToolCall 的孤立 ToolMessage 不是中断遗留，不能凭空补造调用。
    interaction = batch("bad", 2, 1)
    with pytest.raises(ContextInvariantError) as caught:
        await ContextManager().prepare(
            [HumanMessage(content="分析基金"), *interaction[1:]],
            system_message="SYS",
            request=ContextRequest(max_context_tokens=4000),
        )
    assert caught.value.code == "INVALID_TOOL_TRACE"


async def test_dangling_tool_call_is_repaired_not_rejected():
    # 工具节点被打断（断连/重启）会留下没有结果的 AI ToolCall。拒绝它等于让这个
    # 会话此后每轮都失败，所以组装时补一条 RUN_INTERRUPTED 结果，配对照旧完整。
    interaction = batch("bad", 2, 1)
    prepared = await ContextManager().prepare(
        [HumanMessage(content="分析基金"), *interaction[:-1]],
        system_message="SYS",
        request=ContextRequest(max_context_tokens=4000),
    )
    assert_paired(prepared.messages)
    repaired = [m for m in prepared.messages if isinstance(m, ToolMessage) and "RUN_INTERRUPTED" in str(m.content)]
    assert len(repaired) == 1
    assert repaired[0].tool_call_id == "bad_1"


@pytest.mark.parametrize("fits", [True, False])
def test_legacy_budget_never_splits_batch(monkeypatch, fits: bool):
    human = HumanMessage(content="分析基金")
    latest = batch("latest", 4)
    budget = token_estimator.count_messages([human, *latest]) + (10 if fits else -10)
    monkeypatch.setattr(settings, "CONTEXT_TOKEN_BUDGET", budget)
    result = _fit_budget([human, *batch("old", 2, 400), *latest])
    assert result == [human, *latest] if fits else result == [human]
    assert_paired(result)


@pytest.mark.parametrize(
    "text", ["持仓行情数据" * 3000, "📈股票上涨🙂" * 3000, '{"行情":"上涨"}' * 3000], ids=["chinese", "emoji", "json"]
)
@pytest.mark.parametrize("limit", [8, 100, 4000])
def test_tool_hard_limit_counts_tokens_including_marker(text: str, limit: int):
    original = ToolMessage(content=text, tool_call_id="call", name="market", id="message-id")
    messages, compacted = hard_limit_tool_trace([original], token_estimator, limit)
    assert compacted == 1
    assert token_estimator.count_text(messages[0].content) <= limit
    assert "TRUNCATED" in messages[0].content
    assert messages[0].tool_call_id == "call"
    assert messages[0].name == "market"
    assert messages[0].id == "message-id"
    assert original.content == text


@pytest.mark.parametrize("streaming", [False, True])
async def test_agent_completes_batched_tools_after_budget_pruning(monkeypatch, streaming: bool):
    """Run the real graph and both response paths, keeping full checkpoint history."""
    monkeypatch.setattr(settings, "CONTEXT_TOKEN_BUDGET", 4500)
    monkeypatch.setattr(settings, "CONTEXT_STRATEGY", "structured")
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    monkeypatch.setattr(settings, "LANGFUSE_TRACING_ENABLED", False)
    monkeypatch.setattr("app.agent.graph.agent.load_system_prompt", lambda **kwargs: "SYS")
    old_call = AIMessage(content="", tool_calls=[{"id": "old", "name": "old_tool", "args": {"size": 1200}}])
    latest_call = AIMessage(
        content="",
        tool_calls=[{"id": f"new_{i}", "name": f"tool_{i}", "args": {"size": 120}} for i in range(4)],
    )
    model = FakeMessagesListChatModel(responses=[old_call, latest_call, AIMessage(content="分析完成")])
    seen: list[list] = []

    class ScriptedService:
        def get_llm(self):
            return None

        async def call(self, messages):
            assert_paired(messages)
            seen.append(messages)
            return await model.ainvoke(messages)

    async def result(size: int) -> str:
        return "行情数据" * size

    agent = LangGraphAgent()
    agent.llm_service = ScriptedService()
    agent._tool_schemas = []
    agent.tools_by_name = {
        name: StructuredTool.from_function(coroutine=result, name=name, description="test market data")
        for name in ["old_tool", *(f"tool_{i}" for i in range(4))]
    }
    agent._graph = agent._build_graph(InMemorySaver())
    thread = f"batched-budget-{streaming}"
    messages = [Message(role="user", content="分析我的基金")]
    if streaming:
        chunks = [chunk async for chunk in agent.get_stream_response(messages, thread, user_id="42")]
        assert "分析完成" in "".join(chunks)
    else:
        response = await agent.get_response(messages, thread, user_id="42")
        assert response[-1].content == "分析完成"
    assert len(seen) == 3
    assert {m.tool_call_id for m in seen[-1] if isinstance(m, ToolMessage)} == {f"new_{i}" for i in range(4)}
    checkpoint = await agent._graph.aget_state({"configurable": {"thread_id": thread}})
    assert not checkpoint.next
    history = checkpoint.values["messages"]
    assert {m.tool_call_id for m in history if isinstance(m, ToolMessage)} == {"old", *(f"new_{i}" for i in range(4))}
    assert_paired(history)
