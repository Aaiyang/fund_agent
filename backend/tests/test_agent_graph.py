"""LangGraph agent 循环（chat → tool → chat）的集成测试.

这里跑的是 ``LangGraphAgent`` 真实的节点实现，配上内存 checkpointer 和按脚本回放的
假 LLM，于是整张图 —— 工具分发、未知工具的兜底、ask_human 的中断与恢复 —— 都能在
不依赖 Postgres、也不依赖真实模型的情况下完整走一遍。
"""

import asyncio

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import LangGraphAgent
from app.schemas import Message


async def _drain_background_tasks() -> None:
    """断言之前，先让发后即办的任务（记忆写入）跑完."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _message_as_dict(message):
    """BaseMessage 或 dict 统一转成测试断言用的字典."""
    if isinstance(message, dict):
        return message
    return {
        "type": getattr(message, "type", None),
        "content": getattr(message, "content", ""),
        "tool_call_id": getattr(message, "tool_call_id", None),
    }


class FakeLLMService:
    """LLMService 的脚本化替身：每次 call() 弹出一条 AIMessage."""

    def __init__(self, scripted: list[AIMessage]):
        self.scripted = list(scripted)
        self.calls: list[list[dict]] = []

    def get_llm(self):
        # 返回 None，让 _chat 走 settings.DEFAULT_LLM_MODEL 那条兜底分支。
        return None

    async def call(self, messages, *args, **kwargs):
        self.calls.append([_message_as_dict(m) for m in messages])
        return self.scripted.pop(0)


class FakeMemoryService:
    """记下 search()/add() 的调用，绝不碰 mem0."""

    def __init__(self):
        self.searched: list[tuple] = []
        self.added: list[tuple] = []

    async def search(self, user_id, query):
        self.searched.append((user_id, query))
        return ""

    async def add(self, user_id, messages, metadata=None):
        self.added.append((user_id, messages))


def _tool_call_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def _build_agent(monkeypatch, scripted: list[AIMessage]) -> tuple[LangGraphAgent, FakeLLMService, FakeMemoryService]:
    agent = LangGraphAgent()
    fake_llm = FakeLLMService(scripted)
    fake_memory = FakeMemoryService()
    monkeypatch.setattr(agent, "llm_service", fake_llm)
    monkeypatch.setattr("app.agent.graph.agent.memory_service", fake_memory)
    # 注入内存里的图，这样 get_response/get_stream_response 永远碰不到
    # _get_graph() → create_graph() → 真实的 Postgres 连接池。
    agent._graph = agent._build_graph(InMemorySaver())
    return agent, fake_llm, fake_memory


async def test_plain_response_round_trip(monkeypatch):
    from app.core.config import settings

    # 会话快照策略下，记忆检索只在会话首次调用时发生
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", True)
    agent, fake_llm, fake_memory = _build_agent(monkeypatch, [AIMessage(content="hello there")])
    config = {"configurable": {"thread_id": "t1"}}

    result = await agent.get_response([Message(role="user", content="hi")], "t1", user_id="u1")

    # get_response 返回整条会话线（输入的那条消息也在里面）。
    assert result == [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello there"),
    ]
    # 只发起了一次 LLM 调用，记忆检索用的就是用户这句话。
    assert len(fake_llm.calls) == 1
    assert fake_memory.searched == [("u1", "hi")]
    # 记忆写入在后台进行，喂进去的是最终那份 openai 风格的消息。
    await _drain_background_tasks()
    assert len(fake_memory.added) == 1
    added_user_id, added_messages = fake_memory.added[0]
    assert added_user_id == "u1"
    assert [m["role"] for m in added_messages] == ["user", "assistant"]

    # checkpointer 留下了这条会话线：历史一直存到 state 里。
    state = await agent._graph.aget_state(config)
    assert len(state.values["messages"]) == 2


async def test_unknown_tool_name_recovers(monkeypatch):
    agent, fake_llm, _ = _build_agent(
        monkeypatch,
        [
            _tool_call_message("no_such_tool", {}, "call_1"),
            AIMessage(content="recovered"),
        ],
    )

    result = await agent.get_response([Message(role="user", content="do something")], "t2", user_id="u2")

    # 这道防护加上之前，模型编造出来的工具名会把节点打挂（KeyError 重试 3 次后
    # 变成 500）。现在错误会以 ToolMessage 的形式送回去，模型才有机会自己纠正。
    assert result[-1] == Message(role="assistant", content="recovered")
    assert len(fake_llm.calls) == 2
    # LangChain 风格的字典带的是 "type"，不是 openai 的 "role"。
    tool_messages = [m for m in fake_llm.calls[1] if m.get("type") == "tool"]
    assert len(tool_messages) == 1
    assert "no_such_tool" in tool_messages[0]["content"]


async def test_tool_result_reaches_model(monkeypatch):
    agent, fake_llm, _ = _build_agent(
        monkeypatch,
        [
            _tool_call_message("echo_tool", {"query": "fund nav"}, "call_1"),
            AIMessage(content="search done"),
        ],
    )

    # 注册一个替身工具，测试全程不会碰真实网络。
    async def _echo(query: str) -> str:
        return f"echo: {query}"

    echo_tool = StructuredTool.from_function(coroutine=_echo, name="echo_tool", description="echoes the query")
    monkeypatch.setattr(agent, "tools_by_name", {"echo_tool": echo_tool})

    result = await agent.get_response([Message(role="user", content="search for funds")], "t3", user_id="u3")

    assert result[-1] == Message(role="assistant", content="search done")
    tool_messages = [m for m in fake_llm.calls[1] if m.get("type") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"] == "echo: fund nav"
    assert tool_messages[0]["tool_call_id"] == "call_1"


async def test_ask_human_interrupt_and_resume(monkeypatch):
    agent, fake_llm, _ = _build_agent(
        monkeypatch,
        [
            _tool_call_message("ask_human", {"question": "Proceed with purchase?"}, "call_1"),
            AIMessage(content="purchase confirmed"),
        ],
    )

    # 第一次调用：图在 ask_human 处中断，把问题原样抛到上层。
    first = await agent.get_response([Message(role="user", content="buy fund A")], "t4", user_id="u4")
    assert first == [Message(role="assistant", content="Proceed with purchase?")]
    # 到目前为止只消耗掉脚本里的第一条回复。
    assert len(fake_llm.calls) == 1

    # 第二次调用：用户的回复让被中断的工具节点接着跑。用于恢复的那条输入不会追加进
    # 会话线 —— 它只喂给工具 —— 所以返回的会话线是「原来的用户消息 + 最终答复」。
    second = await agent.get_response([Message(role="user", content="yes please")], "t4", user_id="u4")
    assert second == [
        Message(role="user", content="buy fund A"),
        Message(role="assistant", content="purchase confirmed"),
    ]

    # 恢复时传入的那个值，作为 ask_human 工具的结果回到了模型面前。
    tool_messages = [m for m in fake_llm.calls[1] if m.get("type") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"] == "yes please"
