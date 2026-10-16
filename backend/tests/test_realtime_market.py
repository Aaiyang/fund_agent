"""实时指数契约：时间真实性、成功缓存、部分失败和真实 Agent 图执行."""

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.market import get_realtime_market
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, MARKET_TOOLS, TOOLS_VERSION
from app.core.cache import InMemoryCacheService
from app.core.config import settings
from app.integrations.fund_data.models import MarketExternalQuote
from app.integrations.fund_data.tencent_client import fetch_quotes
from app.schemas import Message
from app.schemas.market import RealtimeMarketRequest
from app.services.market_service import MarketService, REALTIME_INDEXES
from app.utils.market_quote_policy import normalize_realtime_index

market_module = importlib.import_module("app.services.market_service")
tool_module = importlib.import_module("app.agent.tools.market.get_realtime_market")
tencent_module = importlib.import_module("app.integrations.fund_data.tencent_client")
SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 9, 14, 5, 30, tzinfo=SHANGHAI)


def quote(code="sh000001", **changes):
    return MarketExternalQuote.model_validate(
        {
            "symbol": code,
            "kind": "index",
            "name": REALTIME_INDEXES[code],
            "price": 3800.0,
            "change": 38.0,
            "change_pct": 1.0,
            "prev_close": 3762.0,
            "amount": 700_000_000_000.0,
            "quote_time": "2026-10-09 14:05:20",
            **changes,
        }
    )


@pytest.fixture
def market(monkeypatch):
    calls = []
    rows = [quote(code) for code in REALTIME_INDEXES]
    cache = InMemoryCacheService()

    async def fetch(codes):
        calls.append(codes)
        return [item for item in rows if item.symbol in codes]

    monkeypatch.setattr(market_module, "fetch_quotes", fetch)
    monkeypatch.setattr(market_module, "cache_service", cache)
    monkeypatch.setattr(market_module, "business_now", lambda: NOW)
    monkeypatch.setattr(market_module, "utc_now", lambda: NOW.astimezone(UTC).replace(tzinfo=None))
    return SimpleNamespace(service=MarketService(), calls=calls, rows=rows, cache=cache)


@pytest.mark.parametrize(
    ("timestamp", "freshness"),
    [
        ("2026-10-09 14:05:20", "same_day"),
        ("2026-10-08 15:00:00", "previous_session"),
        ("2026-10-09 14:01:00", "delayed"),
        ("2026-10-09 14:10:00", "future_time"),
        ("2026-10-10 14:05:00", "future_time"),
        ("2026-10-09 99:99:99", "unknown_time"),
        ("2026-10-09", "unknown_time"),
        (None, "unknown_time"),
    ],
)
def test_quote_time_cannot_be_replaced_by_fetch_time(timestamp, freshness):
    result = normalize_realtime_index(quote(quote_time=timestamp), "上证指数", NOW)
    assert result is not None
    assert result.freshness == freshness
    assert result.stale is (freshness != "same_day")
    if freshness == "unknown_time":
        assert result.quote_time is None and result.trade_date is None
    else:
        assert result.quote_time.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize(
    ("hour", "minute", "timestamp", "expected_stale"),
    [
        (12, 30, "2026-10-09 11:30:00", False),
        (12, 30, "2026-10-09 10:30:00", True),
        (17, 30, "2026-10-09 15:00:00", False),
        (17, 30, "2026-10-09 14:00:00", True),
        (13, 5, "2026-10-09 11:30:00", True),
    ],
)
def test_lunch_and_close_do_not_hide_old_quotes(hour, minute, timestamp, expected_stale):
    result = normalize_realtime_index(quote(quote_time=timestamp), "上证指数", NOW.replace(hour=hour, minute=minute))
    assert result is not None and result.stale is expected_stale


@pytest.mark.parametrize("price", [None, 0, -1, float("nan"), float("inf")])
def test_invalid_price_is_missing_instead_of_zero(price):
    assert normalize_realtime_index(quote(price=price), "上证指数", NOW) is None


def test_nonfinite_change_is_unknown_and_zero_change_is_preserved():
    result = normalize_realtime_index(quote(change=0, change_pct=float("inf")), "上证指数", NOW)
    assert result is not None and result.change == 0 and result.change_pct is None


async def test_defaults_batch_all_indexes_and_preserve_units(market):
    response = await market.service.get_realtime_quotes(RealtimeMarketRequest())
    assert market.calls == [list(REALTIME_INDEXES)]
    assert response is not None and len(response.indexes) == 14
    assert response.indexes[0].change_pct == 1.0
    assert response.indexes[0].amount == 700_000_000_000.0
    assert response.fetched_at.tzinfo is None
    assert response.fetched_at_timezone == "UTC" and response.timezone == "Asia/Shanghai"
    assert not response.stale and not response.missing_indexes


async def test_subset_deduplicates_and_cached_result_preserves_request_order(market):
    first = RealtimeMarketRequest(index_codes=["sz399001", "sh000001", "sz399001"])
    await market.service.get_realtime_quotes(first)
    response = await market.service.get_realtime_quotes(
        RealtimeMarketRequest(index_codes=["sh000001", "sz399001"], refresh=False)
    )
    assert market.calls == [["sz399001", "sh000001"]]
    assert response is not None and response.from_cache
    assert [item.index_code for item in response.indexes] == ["sh000001", "sz399001"]


async def test_default_refresh_bypasses_success_cache(market):
    await market.service.get_realtime_quotes(RealtimeMarketRequest())
    response = await market.service.get_realtime_quotes(RealtimeMarketRequest())
    assert len(market.calls) == 2 and response is not None and not response.from_cache


async def test_partial_or_stale_data_is_not_cached(market):
    market.rows[:] = [quote(quote_time="2026-10-08 15:00:00")]
    response = await market.service.get_realtime_quotes(RealtimeMarketRequest(refresh=False))
    assert response is not None and response.stale and len(response.missing_indexes) == 13
    await market.service.get_realtime_quotes(RealtimeMarketRequest(refresh=False))
    assert len(market.calls) == 2


async def test_missing_change_is_not_zero_or_cached(market):
    market.rows[:] = [quote(change_pct=None)]
    request = RealtimeMarketRequest(index_codes=["sh000001"], refresh=False)
    first = await market.service.get_realtime_quotes(request)
    await market.service.get_realtime_quotes(request)
    assert first is not None and first.indexes[0].change_pct is None and len(market.calls) == 2


async def test_empty_and_failure_do_not_cache_or_fall_back_to_history(market, monkeypatch):
    market.rows.clear()
    history = AsyncMock(side_effect=AssertionError("实时查询不应访问日线数据库"))
    monkeypatch.setattr(market.service, "get_quotes", history)
    assert await market.service.get_realtime_quotes(RealtimeMarketRequest()) is None
    failing = AsyncMock(side_effect=httpx.ConnectError("private upstream detail"))
    monkeypatch.setattr(market_module, "fetch_quotes", failing)
    with pytest.raises(httpx.ConnectError):
        await market.service.get_realtime_quotes(RealtimeMarketRequest(refresh=False))
    assert not history.called
    monkeypatch.setattr(tool_module, "market_service", market.service)
    text = await get_realtime_market.ainvoke({})
    assert text.startswith("[TOOL_ERROR] UPSTREAM_ERROR") and "private upstream detail" not in text


async def test_expired_cache_and_midnight_are_refetched(market, monkeypatch):
    request = RealtimeMarketRequest(index_codes=["sh000001"], refresh=False)
    await market.service.get_realtime_quotes(request)
    later = NOW + timedelta(seconds=16)
    monkeypatch.setattr(market_module, "utc_now", lambda: later.astimezone(UTC).replace(tzinfo=None))
    await market.service.get_realtime_quotes(request)
    assert len(market.calls) == 2
    monkeypatch.setattr(market_module, "business_now", lambda: NOW + timedelta(days=1))
    response = await market.service.get_realtime_quotes(request)
    assert len(market.calls) == 3 and response is not None and response.stale


async def test_cache_outage_does_not_break_live_quotes(market, monkeypatch):
    broken = SimpleNamespace(
        get=AsyncMock(side_effect=RuntimeError("cache read")), set=AsyncMock(side_effect=RuntimeError("cache write"))
    )
    monkeypatch.setattr(market_module, "cache_service", broken)
    result = await market.service.get_realtime_quotes(RealtimeMarketRequest(refresh=False))
    assert result is not None and len(result.indexes) == 14


@pytest.mark.parametrize("codes", [["sh600519"], ["https://example.com"], [], ["sh000001"] * 15])
def test_request_rejects_stocks_urls_empty_and_unbounded_queries(codes):
    with pytest.raises(ValidationError):
        RealtimeMarketRequest(index_codes=codes)


async def test_service_rechecks_whitelist_before_network(market):
    bypass = RealtimeMarketRequest.model_construct(index_codes=["https://example.com"])
    with pytest.raises(ValueError):
        await market.service.get_realtime_quotes(bypass)
    assert not market.calls


async def test_tool_reports_each_quote_time_and_oldest_as_of(market, monkeypatch):
    market.rows[:] = [quote(), quote("sz399001", quote_time="2026-10-09 14:05:10")]
    monkeypatch.setattr(tool_module, "market_service", market.service)
    text = await get_realtime_market.ainvoke({"index_codes": ["sh000001", "sz399001"]})
    payload = json.loads(text.splitlines()[1])
    assert text.startswith("[TOOL_OK]") and "as_of=2026-10-09T14:05:10+08:00" in text
    assert payload["indexes"][0]["quote_time"] == "2026-10-09T14:05:20+08:00"
    assert payload["from_cache"] is False and "成分可能重叠" in text


async def test_empty_tool_returns_safe_error(market, monkeypatch):
    market.rows.clear()
    monkeypatch.setattr(tool_module, "market_service", market.service)
    assert (await get_realtime_market.ainvoke({})).startswith("[TOOL_ERROR] DATA_NOT_AVAILABLE")


def test_registry_and_schema_keep_public_query_bounded():
    assert get_realtime_market in MARKET_TOOLS and get_realtime_market in DEFAULT_AGENT_TOOLS
    assert TOOLS_VERSION == "v20" and set(get_realtime_market.args) == {"index_codes", "refresh"}


@pytest.mark.parametrize("stream", [False, True])
async def test_three_new_turns_can_refresh_the_same_market_tool(market, monkeypatch, stream):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(tool_module, "market_service", market.service)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)

    class ScriptedLLM:
        calls = 0

        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            latest = next(message for message in reversed(inputs) if message.type != "system")
            if latest.type != "tool":
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_realtime_market",
                            "args": {},
                            "id": f"market-call-{self.calls}",
                            "type": "tool_call",
                        }
                    ],
                )
            assert latest.content.startswith("[TOOL_OK]")
            return AIMessage(content="主要指数报价已刷新，时间见行情表。")

    monkeypatch.setattr(agent, "llm_service", ScriptedLLM())
    for _ in range(3):
        messages = [Message(role="user", content="刷新今天大盘行情")]
        if stream:
            async for _ in agent.get_stream_response(messages, "market-test", user_id="42"):
                pass
            response = await agent.get_chat_history("market-test")
        else:
            response = await agent.get_response(messages, "market-test", user_id="42")
        assert response[-1].role == "assistant"
    assert len(market.calls) == 3


async def test_realtime_http_contract_batches_and_decodes_provider_fields(monkeypatch):
    fields = [""] * 88
    for offset, value in {
        1: "北证50",
        2: "899050",
        3: "1026.65",
        4: "1012.08",
        5: "1012.9",
        6: "1000",
        30: "20261009140521",
        31: "14.57",
        32: "1.44",
        33: "1030",
        34: "1010",
        35: "1026.65/1000/13044649527",
        43: "1.98",
        82: "CNY",
    }.items():
        fields[offset] = value
    payload = f'v_bj899050="{"~".join(fields)}";'
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=payload.encode("gbk"), headers={"Content-Type": "text/plain; charset=gbk"})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        tencent_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await fetch_quotes(["sh000001", "bj899050"])
    assert len(requests) == 1 and str(requests[0].url).endswith("q=sh000001,bj899050")
    assert len(result) == 1 and result[0].kind == "index" and result[0].name == "北证50"
    assert result[0].change_pct == 1.44 and result[0].amount == 13044649527.0
    assert result[0].quote_time == "2026-10-09 14:05:21"


async def test_same_turn_repeated_tool_still_stops_after_two_queries(market, monkeypatch):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(tool_module, "market_service", market.service)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)

    class RepeatingLLM:
        count = 0

        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            latest = next(message for message in reversed(inputs) if message.type != "system")
            if latest.type == "tool" and "DUPLICATE_TOOL_CALL" in latest.content:
                return AIMessage(content="本轮行情已经查询，请使用已有结果。")
            self.count += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_realtime_market", "args": {}, "id": f"loop-{self.count}", "type": "tool_call"}
                ],
            )

    monkeypatch.setattr(agent, "llm_service", RepeatingLLM())
    response = await agent.get_response([Message(role="user", content="今天大盘行情")], "market-loop", user_id="42")
    assert response[-1].role == "assistant" and len(market.calls) == 2
