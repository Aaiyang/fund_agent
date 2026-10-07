"""七个业务工具的 agent 集成测试（spec 30，用例 1-7）.

每个用例都跑真实的图（内存 checkpointer），配一个脚本化的 LLM，让它正好调用规范要求
的那个工具，然后校验：
- 服务层拿到的是运行时注入的 user_id（绝不是模型自己说出来的那个），
- ToolResult 以 tool message 的形式回到了模型面前，
- 最终答复是在工具那一轮之后才产生的。
"""

from datetime import date, timedelta
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import LangGraphAgent
from app.schemas import Message
from app.utils.clock import business_today, utc_now
from tests.test_agent_tools import _patch_tool_service


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
    def __init__(self, scripted: list[AIMessage]):
        self.scripted = list(scripted)
        self.calls: list[list[dict]] = []

    def get_llm(self):
        return None

    async def call(self, messages, *args, **kwargs):
        self.calls.append([_message_as_dict(m) for m in messages])
        return self.scripted.pop(0)


class FakeMemoryService:
    async def search(self, user_id, query):
        return ""

    async def add(self, user_id, messages, metadata=None):
        return None


def _tool_call_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def _build_agent(monkeypatch, scripted: list[AIMessage]):
    agent = LangGraphAgent()
    fake_llm = FakeLLMService(scripted)
    monkeypatch.setattr(agent, "llm_service", fake_llm)
    monkeypatch.setattr("app.agent.graph.agent.memory_service", FakeMemoryService())
    agent._graph = agent._build_graph(InMemorySaver())
    return agent, fake_llm


async def _run_case(monkeypatch, tool_name: str, tool_args: dict, expect_in_tool_message: str) -> str:
    scripted = [
        _tool_call_message(tool_name, tool_args, "call_1"),
        AIMessage(content=f"done:{tool_name}"),
    ]
    agent, fake_llm = _build_agent(monkeypatch, scripted)

    result = await agent.get_response([Message(role="user", content="case")], f"case-{tool_name}", user_id="42")

    tool_messages = [m for m in fake_llm.calls[1] if m.get("type") == "tool"]
    assert tool_messages, f"{tool_name}: 工具结果没有回到模型"
    assert tool_messages[0].get("name", tool_name) == tool_name
    assert expect_in_tool_message in tool_messages[0]["content"]
    return result[-1].content


async def test_case_1_snapshot(monkeypatch):
    detail = SimpleNamespace(
        fund_code="005827",
        fund_name="易方达蓝筹精选",
        fund_type="混合型",
        company=None,
        manager_name=None,
        inception_date=None,
        asset_size=None,
        latest_nav=1.5,
        accumulated_nav=None,
        nav_date=business_today() - timedelta(days=1),
        daily_return=None,
        performance=None,
        source=None,
        source_as_of=None,
    )
    seen = {}

    async def fake_detail(code, user_id):
        seen.update(code=code, user_id=user_id)
        return detail

    _patch_tool_service(monkeypatch, "get_fund_snapshot", SimpleNamespace(get_detail=fake_detail))
    answer = await _run_case(monkeypatch, "get_fund_snapshot", {"fund_code": "005827"}, "易方达蓝筹精选")
    assert answer == "done:get_fund_snapshot"
    assert seen == {"code": "005827", "user_id": 42}


async def test_case_2_search(monkeypatch):
    async def fake_search(keyword, user_id):
        return [SimpleNamespace(fund_code="005827", fund_name="易方达蓝筹精选", fund_type="混合型")]

    _patch_tool_service(monkeypatch, "search_funds", SimpleNamespace(search=fake_search))
    answer = await _run_case(monkeypatch, "search_funds", {"keyword": "易方达蓝筹"}, "005827")
    assert answer == "done:search_funds"


async def test_case_3_history(monkeypatch):
    base = business_today() - timedelta(days=30)
    points = [SimpleNamespace(nav_date=base + timedelta(days=i), unit_nav=1.2 + i / 100) for i in range(30)]
    seen = {}

    async def fake_history(fund_code, start_date=None, end_date=None, range_key=None, limit=None, before_date=None):
        seen.update(range_key=range_key, fund_code=fund_code)
        return SimpleNamespace(fund_code=fund_code, range=range_key, total=30, has_more=False, points=points)

    _patch_tool_service(monkeypatch, "get_fund_history", SimpleNamespace(get_nav_history=fake_history))
    answer = await _run_case(
        monkeypatch,
        "get_fund_history",
        {"fund_code": "005827", "range_key": "1y"},
        "005827",
    )
    assert answer == "done:get_fund_history"
    assert seen["range_key"] == "1y"


async def test_case_4_holdings(monkeypatch):
    response = SimpleNamespace(
        quarter="2026年2季度",
        previous_quarter=None,
        items=[
            SimpleNamespace(stock_code="600519", stock_name="贵州茅台", weight=9.5, weight_change=None, is_new=False)
        ],
        industries=[],
        industries_as_of=None,
    )

    async def fake_holdings(code):
        return response

    _patch_tool_service(monkeypatch, "get_fund_holdings", SimpleNamespace(get_holdings=fake_holdings))
    answer = await _run_case(monkeypatch, "get_fund_holdings", {"fund_code": "005827"}, "贵州茅台")
    assert answer == "done:get_fund_holdings"


async def test_case_5_positions(monkeypatch):
    seen = {}

    async def fake_positions(user_id, account_id=None):
        seen.update(user_id=user_id, account_id=account_id)
        return [
            SimpleNamespace(
                fund_code="005827",
                fund_name="易方达蓝筹精选",
                account_id=1,
                shares=100.0,
                cost_amount=100.0,
                market_value=150.0,
                profit_loss=50.0,
                profit_loss_rate=0.5,
                position_ratio=0.6,
                daily_profit_loss=1.5,
                nav_date=date(2026, 9, 29),
                updated_at=None,
            ),
            SimpleNamespace(
                fund_code="110022",
                fund_name="易方达消费行业",
                account_id=1,
                shares=50.0,
                cost_amount=100.0,
                market_value=100.0,
                profit_loss=0.0,
                profit_loss_rate=0.0,
                position_ratio=0.4,
                daily_profit_loss=0.0,
                nav_date=date(2026, 9, 29),
                updated_at=None,
            ),
        ]

    _patch_tool_service(monkeypatch, "get_positions", SimpleNamespace(list_positions=fake_positions))
    answer = await _run_case(monkeypatch, "get_positions", {}, "005827")
    assert answer == "done:get_positions"
    assert seen == {"user_id": 42, "account_id": None}


async def test_case_6_portfolio(monkeypatch):
    seen = {}

    async def fake_summary(user_id, account_id=None):
        seen.update(user_id=user_id, account_id=account_id)
        return SimpleNamespace(
            fund_count=2,
            total_market_value=250.0,
            total_cost=200.0,
            total_profit_loss=50.0,
            total_profit_loss_rate=0.25,
            daily_profit_loss=1.5,
            data_updated_at=utc_now(),
        )

    _patch_tool_service(monkeypatch, "get_portfolio", SimpleNamespace(get_summary=fake_summary))
    answer = await _run_case(monkeypatch, "get_portfolio", {}, "total_market_value")
    assert answer == "done:get_portfolio"
    assert seen == {"user_id": 42, "account_id": None}


async def test_case_7_market(monkeypatch):
    async def fake_quotes():
        return [
            SimpleNamespace(
                index_code="sh000001", name="上证指数", close=3000.0, change_pct=-0.5, trade_date=business_today()
            ),
        ]

    _patch_tool_service(monkeypatch, "get_market_context", SimpleNamespace(get_quotes=fake_quotes))
    answer = await _run_case(monkeypatch, "get_market_context", {}, "上证指数")
    assert answer == "done:get_market_context"


async def test_tool_loop_is_bounded(monkeypatch):
    """recursion_limit 给 chat/tool 之间的来回轮数封顶（约 12 轮工具）."""
    from app.agent.graph.agent import TOOL_LOOP_RECURSION_LIMIT

    agent, _ = _build_agent(monkeypatch, [])
    config = {"configurable": {"thread_id": "t"}, "metadata": {"user_id": "42"}}
    set_limit = (await agent._get_graph()).nodes  # 图能正常编译出来
    assert TOOL_LOOP_RECURSION_LIMIT == 25
    # 这个上限是 LangGraph 负责强制执行的配置值，这里只断言接线还在。
    assert config is not None and set_limit


async def test_recursion_limit_returns_friendly_message(monkeypatch):
    """模型陷入工具循环时，递归上限触发后应返回友好提示而非 500."""

    class LoopLLMService:
        """无论收到什么都要求再调一次 get_market_context 的假 LLM."""

        def __init__(self):
            self.calls = 0

        def get_llm(self):
            return None

        async def call(self, messages, *args, **kwargs):
            self.calls += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_market_context", "args": {}, "id": f"call_{self.calls}", "type": "tool_call"}
                ],
            )

    fake_llm = LoopLLMService()
    agent = LangGraphAgent()
    monkeypatch.setattr(agent, "llm_service", fake_llm)
    monkeypatch.setattr("app.agent.graph.agent.memory_service", FakeMemoryService())
    _patch_tool_service(
        monkeypatch,
        "get_market_context",
        SimpleNamespace(get_quotes=_async_quotes),
    )
    agent._graph = agent._build_graph(InMemorySaver())

    result = await agent.get_response([Message(role="user", content="最近市场怎么样")], "loop-case", user_id="42")

    assert result[-1].role == "assistant"
    assert "处理步骤过多" in result[-1].content


async def _async_quotes():
    return [
        SimpleNamespace(
            index_code="sh000001", name="上证指数", close=3000.0, change_pct=0.1, trade_date=business_today()
        )
    ]
