"""事件来源核验、覆盖范围、私有持仓隔离及真实Agent工具链."""

import hashlib
import importlib
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.market import get_market_events
from app.agent.tools.portfolio import identify_event_portfolio_links
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, MARKET_TOOLS, PORTFOLIO_TOOLS, TOOLS_VERSION
from app.agent.tools.runtime import ToolRuntimeContext, set_tool_runtime
from app.analytics.event_links import classify_event, link_event
from app.core.cache import InMemoryCacheService, cache_key
from app.core.config import settings
from app.integrations.fund_data.event_client import EventDataUnavailable, fetch_event_feed, parse_event
from app.schemas import Message
from app.schemas.fund import FundIndustryItem
from app.schemas.market_event import EventPortfolioLinkRequest, MarketEventFeed, MarketEventsRequest
from app.schemas.portfolio import PositionItem
from app.schemas.sector import FundSectorEvidence
from app.services.event_portfolio_service import EventPortfolioService, EventReferenceMissing
from app.services.market_event_service import EventReference, MarketEventService, valid_event
from app.services.portfolio_service import AccountNotFoundError

client_module = importlib.import_module("app.integrations.fund_data.event_client")
events_module = importlib.import_module("app.services.market_event_service")
links_module = importlib.import_module("app.services.event_portfolio_service")
event_tool_module = importlib.import_module("app.agent.tools.market.get_market_events")
link_tool_module = importlib.import_module("app.agent.tools.portfolio.identify_event_portfolio_links")
STAMP = datetime(2026, 10, 9, 7, 30)
BUSINESS = STAMP.replace(tzinfo=UTC).astimezone(ZoneInfo("Asia/Shanghai"))


def row(source_id=1, content="【半导体行业消息】芯片产业政策发布", **changes):
    return {
        "id": source_id,
        "content": content,
        "ctime": int(STAMP.replace(tzinfo=UTC).timestamp()) - source_id,
        "level": "A",
        **changes,
    }


def event(source_id=1, content="【半导体行业消息】芯片产业政策发布", **changes):
    result = parse_event(row(source_id, content, **changes))
    assert result is not None
    return result


def fund(code="000001", name="测试芯片基金", industries=None):
    return FundSectorEvidence(
        fund_code=code,
        fund_name=name,
        report_date=date(2026, 6, 30),
        industries=industries if industries is not None else [FundIndustryItem(industry="制造业", weight=70)],
    )


def position(code="000001", account_id=10, value=100):
    return PositionItem(fund_code=code, account_id=account_id, market_value=value)


def test_parser_keeps_public_source_and_time_and_strips_html():
    result = event(content="<script>恶意内容</script>【芯片事件】<b>半导体</b>公告", level={"bad": True})
    assert result.published_at == BUSINESS - timedelta(seconds=1)
    assert result.title == "芯片事件" and "恶意" not in result.excerpt
    assert result.source_url == "https://www.cls.cn/detail/1" and result.source_priority == "unknown"
    assert result.categories == ["industry"] and result.topics == ["半导体"] and valid_event(result)
    long = event(content="芯片" + "甲" * 1000)
    assert len(long.title) <= 180 and len(long.excerpt) == 240


@pytest.mark.parametrize(
    "changes",
    [
        {"id": True},
        {"id": -1},
        {"id": "1"},
        {"ctime": float("nan")},
        {"ctime": True},
        {"content": "<script>x</script>"},
        {"content": None},
    ],
)
def test_parser_rejects_unverifiable_records(changes):
    assert parse_event(row(**changes)) is None


def test_classification_boundaries_and_broad_industry_not_forced():
    assert classify_event("RAIL") == ([], [], [])
    assert classify_event("人民银行降准，CPI同比变化") == (["macro"], [], ["liquidity", "macro_data"])
    assert classify_event("AI芯片 A股市场")[:2] == (["industry", "market"], ["半导体", "人工智能"])
    assert not link_event(event(), fund(name="宽基基金"), 10)
    hint = link_event(event(), fund(), 10)[0]
    assert hint.basis == "fund_name_hint" and hint.impact_direction == "unknown"
    disclosed = link_event(event(), fund(industries=[FundIndustryItem(industry="半导体行业", weight=12)]), 10)[0]
    assert disclosed.basis == "disclosed_industry" and disclosed.disclosure_date == "2026-06-30"
    macro = link_event(event(content="人民银行降息"), fund(name="债券基金"), 10)
    assert [item.basis for item in macro] == ["macro_context"] and macro[0].impact_direction == "unknown"
    market = link_event(event(content="美股指数上涨"), fund(name="国内债券基金"), 10)
    assert market[0].basis == "market_context" and "尚未核验" in market[0].possible_channel


async def test_fixed_source_request_has_no_private_or_query_parameters(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"errno": 0, "data": {"roll_data": [row()]}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert len(await client_module._page(100)) == 1
    request = requests[0]
    assert request.url.host == "www.cls.cn" and request.url.path == "/v1/roll/get_roll_list"
    params = dict(request.url.params)
    signature = params.pop("sign")
    assert signature == hashlib.md5(hashlib.sha1(urlencode(params).encode()).hexdigest().encode()).hexdigest()
    assert params["rn"] == "20" and params["last_time"] == "100"
    assert not {"user_id", "keyword", "holdings", "account_id"}.intersection(params)


@pytest.mark.parametrize(
    "payload",
    [
        {"errno": 1, "data": {}},
        {"errno": 0, "data": {"roll_data": "bad"}},
        {"errno": 0, "data": {"roll_data": [row()] * 21}},
    ],
)
async def test_source_error_and_oversized_page_fail(monkeypatch, payload):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), **kwargs
        ),
    )
    with pytest.raises(EventDataUnavailable):
        await client_module._page(100)


async def test_bounded_pagination_decreases_cursor_and_reports_partial(monkeypatch):
    monkeypatch.setattr(client_module, "utc_now", lambda: STAMP)
    pages = AsyncMock(side_effect=[[row(1)], [row(2)], []])
    monkeypatch.setattr(client_module, "_page", pages)
    result = await fetch_event_feed()
    assert result.scanned_count == 2 and not result.partial and not result.page_limit_reached
    cursors = [call.args[0] for call in pages.await_args_list]
    assert cursors == sorted(cursors, reverse=True) and len(set(cursors)) == 3
    pages.side_effect = [[row(1)], httpx.ConnectError("private detail")]
    result = await fetch_event_feed()
    assert len(result.events) == 1 and result.partial
    pages.side_effect = [[row(1)], [row(1)]]
    assert (await fetch_event_feed()).partial


async def test_scan_cap_invalid_record_and_empty_are_not_no_events(monkeypatch):
    monkeypatch.setattr(client_module, "utc_now", lambda: STAMP)
    pages = AsyncMock(side_effect=[[row(i)] for i in range(1, 6)])
    monkeypatch.setattr(client_module, "_page", pages)
    assert (await fetch_event_feed()).page_limit_reached and pages.await_count == 5
    pages.side_effect = [[row(), row(id=False)], []]
    result = await fetch_event_feed()
    assert result.partial and result.invalid_count == 1
    pages.side_effect = [[], []]
    with pytest.raises(EventDataUnavailable):
        await fetch_event_feed()
    pages.side_effect = httpx.ConnectError("credentials")
    with pytest.raises(httpx.ConnectError):
        await fetch_event_feed()


@pytest.fixture
def services(monkeypatch):
    cache = InMemoryCacheService()
    fetch = AsyncMock(
        return_value=MarketEventFeed(
            events=[event(), event(2, "银行降息", level="C")], fetched_at=STAMP, scanned_count=2
        )
    )
    monkeypatch.setattr(events_module, "cache_service", cache)
    monkeypatch.setattr(events_module, "utc_now", lambda: STAMP)
    monkeypatch.setattr(events_module, "business_now", lambda: BUSINESS)
    monkeypatch.setattr(events_module, "fetch_event_feed", fetch)
    events = MarketEventService()
    links = EventPortfolioService()
    positions = AsyncMock(return_value=[position()])
    evidence = AsyncMock(return_value=fund())
    monkeypatch.setattr(links_module, "market_event_service", events)
    monkeypatch.setattr(links_module.portfolio_service, "list_positions", positions)
    monkeypatch.setattr(links_module.fund_service, "get_sector_evidence", evidence)
    monkeypatch.setattr(links_module, "utc_now", lambda: STAMP)
    monkeypatch.setattr(event_tool_module, "market_event_service", events)
    monkeypatch.setattr(link_tool_module, "event_portfolio_service", links)
    set_tool_runtime(None)
    yield SimpleNamespace(cache=cache, fetch=fetch, events=events, links=links, positions=positions, evidence=evidence)
    set_tool_runtime(None)


async def test_success_cache_refresh_expiration_and_local_scope(services, monkeypatch):
    first = await services.events.query(MarketEventsRequest())
    assert len(first.events) == 1 and first.coverage_from == BUSINESS - timedelta(seconds=2)
    assert first.requested_from < first.coverage_from and any("100条" in warning for warning in first.warnings)
    cached = await services.events.query(MarketEventsRequest(important_only=False, scope="macro", keyword="降息"))
    assert cached.from_cache and len(cached.events) == 1 and cached.events[0].source_priority == "C"
    assert services.fetch.await_count == 1 and cached.fetched_at == STAMP
    await services.events.query(MarketEventsRequest(refresh=True))
    monkeypatch.setattr(events_module, "utc_now", lambda: STAMP + timedelta(seconds=61))
    await services.events.query(MarketEventsRequest())
    assert services.fetch.await_count == 3
    services.fetch.assert_awaited_with()


async def test_empty_match_and_historic_publish_dates_do_not_become_today(services):
    old = event(1, ctime=int((STAMP - timedelta(days=2)).replace(tzinfo=UTC).timestamp()))
    services.fetch.return_value = MarketEventFeed(events=[old], fetched_at=STAMP)
    result = await services.events.query(MarketEventsRequest())
    assert not result.events and result.coverage_to.date() == date(2026, 10, 7)
    assert any("空匹配不代表" in note for note in result.warnings)
    result = await services.events.query(MarketEventsRequest(lookback_hours=72))
    assert result.events[0].published_at == old.published_at


async def test_partial_or_failed_feed_not_cached_and_errors_safe(services):
    services.fetch.return_value.partial = True
    for _ in range(2):
        assert (await services.events.query(MarketEventsRequest())).partial
    assert services.fetch.await_count == 2
    services.fetch.side_effect = EventDataUnavailable("private credential")
    failed = await get_market_events.ainvoke({"refresh": True})
    assert failed.startswith("[TOOL_ERROR] DATA_NOT_AVAILABLE") and "private credential" not in failed
    services.fetch.side_effect = RuntimeError("private credential")
    failed = await get_market_events.ainvoke({"refresh": True})
    assert failed.startswith("[TOOL_ERROR] UPSTREAM_ERROR") and "private credential" not in failed
    assert (await get_market_events.ainvoke({"keyword": " "})).startswith("[TOOL_ERROR] INVALID_ARGUMENT")


async def test_reference_integrity_expiration_and_unknown_ids(services, monkeypatch):
    result = await services.events.query(MarketEventsRequest())
    item = result.events[0]
    resolved, missing = await MarketEventService().resolve([item.event_id, item.event_id])
    assert len(resolved) == 1 and not missing
    for changes in [{"excerpt": "changed"}, {"topics": ["银行"]}, {"source_url": "https://internal"}]:
        forged = item.model_copy(update=changes)
        assert not valid_event(forged)
        await services.cache.set(
            cache_key("market_event_ref:v1", item.event_id),
            EventReference(event=forged, stored_at=STAMP).model_dump_json(),
        )
        assert (await MarketEventService().resolve([item.event_id]))[1] == [item.event_id]
    monkeypatch.setattr(events_module, "utc_now", lambda: STAMP + timedelta(hours=12))
    assert (await services.events.resolve([item.event_id]))[1] == [item.event_id]
    assert (await services.events.resolve(["cls_99_000000000000"]))[1] == ["cls_99_000000000000"]


async def test_cache_outage_keeps_bounded_reference_fallback(services, monkeypatch):
    monkeypatch.setattr(
        events_module,
        "cache_service",
        SimpleNamespace(get=AsyncMock(side_effect=RuntimeError()), set=AsyncMock(side_effect=RuntimeError())),
    )
    monkeypatch.setattr(events_module, "_MAX_REFERENCES", 1)
    result = await services.events.query(MarketEventsRequest(important_only=False))
    assert len(services.events._references) == 1
    available, missing = await services.events.resolve([item.event_id for item in result.events])
    assert len(available) == 1 and len(missing) == 1


async def test_unknown_reference_stops_before_reading_portfolio(services):
    with pytest.raises(EventReferenceMissing):
        await services.links.identify(42, EventPortfolioLinkRequest(event_ids=["cls_99_000000000000"]))
    services.positions.assert_not_called()


async def test_private_identity_ownership_and_no_private_result_cache(services):
    result = await services.events.query(MarketEventsRequest())
    args = {"event_ids": [result.events[0].event_id]}
    denied = await identify_event_portfolio_links.ainvoke(args)
    assert denied.startswith("[TOOL_ERROR] PERMISSION_DENIED")
    services.positions.assert_not_called()
    set_tool_runtime(ToolRuntimeContext(user_id=42, thread_id="a", request_id=""))
    text = await identify_event_portfolio_links.ainvoke(args)
    assert text.startswith("[TOOL_OK]")
    services.positions.assert_awaited_with(42, None)
    assert "market_value" not in text and "cost_amount" not in text
    public_cache_keys = set(services.cache._cache)
    set_tool_runtime(ToolRuntimeContext(user_id=43, thread_id="b", request_id=""))
    services.positions.return_value = [position("000002", 11)]
    services.evidence.return_value = fund("000002", "宽基基金")
    other = json.loads((await identify_event_portfolio_links.ainvoke(args)).splitlines()[1])
    assert other["associations"] == []
    services.positions.assert_awaited_with(43, None)
    assert set(services.cache._cache) == public_cache_keys
    services.positions.side_effect = AccountNotFoundError("private account")
    denied = await identify_event_portfolio_links.ainvoke({**args, "account_id": 999})
    assert denied.startswith("[TOOL_ERROR] PERMISSION_DENIED") and "private account" not in denied


async def test_unique_evidence_calls_truncation_and_unavailable_not_no_impact(services):
    result = await services.events.query(MarketEventsRequest())
    args = EventPortfolioLinkRequest(event_ids=[result.events[0].event_id], position_limit=3)
    services.positions.return_value = [
        position(value=10),
        position(account_id=11, value=20),
        position("000002", value=30),
        position("000003", value=1),
    ]
    services.evidence.side_effect = lambda code: fund() if code == "000001" else None
    result = await services.links.identify(42, args)
    assert result.total_positions == 4 and result.checked_positions == 3 and result.skipped_positions == 1
    assert result.truncated and result.unavailable_funds == ["000002"]
    assert services.evidence.await_count == 2
    assert {item.account_id for item in result.associations} == {10, 11}
    assert any("资料不可用" in note for note in result.warnings)
    services.evidence.side_effect = RuntimeError("private credential")
    result = await services.links.identify(42, args)
    assert not result.associations and len(result.unavailable_funds) == 2


def test_registry_schema_forbids_identity_raw_event_and_urls():
    assert TOOLS_VERSION == "v21"
    assert get_market_events in MARKET_TOOLS and identify_event_portfolio_links in PORTFOLIO_TOOLS
    assert identify_event_portfolio_links in DEFAULT_AGENT_TOOLS
    assert set(identify_event_portfolio_links.args) == {"event_ids", "account_id", "position_limit"}
    for extra in [
        {"user_id": 43},
        {"events": [{"title": "fake"}]},
        {"url": "https://internal"},
        {"position_limit": 51},
        {"event_ids": ["fake"]},
    ]:
        with pytest.raises(ValidationError):
            EventPortfolioLinkRequest.model_validate({"event_ids": [event().event_id], **extra})
    with pytest.raises(ValidationError):
        MarketEventsRequest(scope="private")


@pytest.mark.parametrize("stream", [False, True])
async def test_agent_chains_verified_events_to_authenticated_holdings_over_new_turns(services, monkeypatch, stream):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)

    class ScriptedLLM:
        count = 0

        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            latest = next(message for message in reversed(inputs) if message.type != "system")
            if latest.type == "tool":
                assert latest.content.startswith("[TOOL_OK]")
                if latest.name == "identify_event_portfolio_links":
                    data = json.loads(latest.content.splitlines()[1])
                    assert data["associations"][0]["impact_direction"] == "unknown"
                    return AIMessage(content="仅有基金名称线索，影响方向未知。")
                data = json.loads(latest.content.splitlines()[1])
                name, arguments = "identify_event_portfolio_links", {"event_ids": [data["events"][0]["event_id"]]}
            else:
                name, arguments = "get_market_events", {"refresh": True}
            self.count += 1
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": arguments, "id": f"event-{self.count}", "type": "tool_call"}],
            )

    monkeypatch.setattr(agent, "llm_service", ScriptedLLM())
    for _ in range(3):
        messages = [Message(role="user", content="查近期事件和我的持仓关系")]
        if stream:
            async for _ in agent.get_stream_response(messages, "event-test", user_id="42"):
                pass
            response = await agent.get_chat_history("event-test")
        else:
            response = await agent.get_response(messages, "event-test", user_id="42")
        assert response[-1].role == "assistant"
    assert services.fetch.await_count == 3 and services.positions.await_count == 3
    assert all(call.args == (42, None) for call in services.positions.await_args_list)
