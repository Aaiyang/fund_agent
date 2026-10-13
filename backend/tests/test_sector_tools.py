"""基金板块证据、行情协议、失败缓存和 Agent 工具串联."""

import importlib
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.fund import get_fund_sectors, get_sector_market
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, FUND_TOOLS, TOOLS_VERSION
from app.core.cache import InMemoryCacheService
from app.core.config import settings
from app.integrations.fund_data.models import MarketExternalQuote
from app.integrations.fund_data.sector_client import SectorDataUnavailable, fetch_sector_catalog, fetch_sector_quote
from app.schemas import Message
from app.schemas.fund import FundIndustryItem
from app.schemas.sector import FundSectorEvidence, SectorItem, SectorMarketRequest
from app.services.fund_service import FundService
from app.services.sector_service import SectorService, match_fund_sectors

client_module = importlib.import_module("app.integrations.fund_data.sector_client")
service_module = importlib.import_module("app.services.sector_service")
fund_module = importlib.import_module("app.services.fund_service")
fund_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_sectors")
market_tool_module = importlib.import_module("app.agent.tools.fund.get_sector_market")
NOW = datetime(2026, 10, 9, 14, 5, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
SECTOR = SectorItem(sector_code="BK1036", name="半导体", sector_type="industry")
CONCEPT = SectorItem(sector_code="BK0917", name="半导体概念", sector_type="concept")


def evidence(**changes):
    return FundSectorEvidence.model_validate(
        {
            "fund_code": "012345",
            "fund_name": "测试半导体混合",
            "fund_type": "混合型",
            "industries": [{"industry": "制造业", "weight": 80}, {"industry": "半导体", "weight": 10}],
            "report_date": "2026-06-30",
            **changes,
        }
    )


def quote(**changes):
    return MarketExternalQuote.model_validate(
        {
            "symbol": SECTOR.sector_code,
            "kind": "index",
            "price": 2503.39,
            "change": -28.22,
            "change_pct": -1.11,
            "quote_time": "2026-10-09T14:05:20+08:00",
            **changes,
        }
    )


def test_disclosure_and_theme_remain_distinct_and_wide_industries_unknown():
    result = match_fund_sectors(evidence(), [SECTOR], 5)
    assert len(result.sectors) == 1
    linked = result.sectors[0]
    assert linked.evidence_type == "disclosed_industry" and linked.disclosed_weight == 10
    assert linked.report_date == date(2026, 6, 30)
    assert result.unmatched_industries[0].industry == "制造业"
    hint = match_fund_sectors(evidence(industries=[{"industry": "制造业", "weight": 80}]), [SECTOR], 5)
    assert hint.sectors[0].evidence_type == "fund_name_hint"
    assert hint.sectors[0].disclosed_weight is None and hint.sectors[0].report_date is None


def test_no_forced_mapping_or_generic_style_classification():
    generic = SectorItem(sector_code="BK0001", name="成长", sector_type="concept")
    result = match_fund_sectors(
        evidence(fund_name="测试成长混合", industries=[{"industry": "金融业", "weight": 70}]), [SECTOR, generic], 5
    )
    assert not result.sectors and result.unmatched_industries[0].industry == "金融业"


@pytest.mark.parametrize("fund_name", ["测试纳斯达克QDII", "测试半导体债券", "测试半导体FOF", "测试恒生科技"])
def test_unsupported_markets_do_not_map_to_mainland_themes(fund_name):
    result = match_fund_sectors(evidence(fund_name=fund_name), [SECTOR], 5)
    assert not result.sectors


def test_multiple_disclosed_sectors_sort_weights_and_truncate():
    bank = SectorItem(sector_code="BK0002", name="银行", sector_type="industry")
    result = match_fund_sectors(
        evidence(industries=[{"industry": "银行", "weight": 40}, {"industry": "半导体", "weight": 10}]),
        [SECTOR, bank],
        1,
    )
    assert result.sectors[0].name == "银行" and result.total_matches == 2 and result.truncated


@pytest.mark.parametrize("object_rows", [False, True])
async def test_catalog_complete_pagination_and_list_or_object_diff(monkeypatch, object_rows):
    calls = []

    async def request(path, params):
        calls.append(params)
        row = {"f12": f"BK000{params['pn']}", "f14": f"sector{params['pn']}"}
        return {"data": {"total": 2, "diff": {"0": row} if object_rows else [row]}}

    monkeypatch.setattr(client_module, "_request_json", request)
    rows = await fetch_sector_catalog("industry")
    assert [row.sector_code for row in rows] == ["BK0001", "BK0002"]
    assert len(calls) == 2 and calls[0]["fid"] == "f12"


@pytest.mark.parametrize(
    "second",
    [
        {"total": 2, "diff": [{"f12": "BK0001", "f14": "duplicate"}]},
        {"total": 2, "diff": []},
        {"total": 3, "diff": [{"f12": "BK0002", "f14": "changed"}]},
    ],
)
async def test_incomplete_catalog_never_returned_as_complete(monkeypatch, second):
    responses = [{"total": 2, "diff": [{"f12": "BK0001", "f14": "one"}]}, second]
    monkeypatch.setattr(client_module, "_request_json", AsyncMock(side_effect=[{"data": row} for row in responses]))
    with pytest.raises(SectorDataUnavailable):
        await fetch_sector_catalog("concept")


async def test_public_http_contract_preserves_scaling_and_source_time(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "rc": 0,
                "data": {
                    "f57": "BK1036",
                    "f59": 2,
                    "f43": 250339,
                    "f169": -2822,
                    "f170": -111,
                    "f86": int(NOW.timestamp()),
                },
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = await fetch_sector_quote(SECTOR)
    assert response.price == 2503.39 and response.change == -28.22 and response.change_pct == -1.11
    assert response.quote_time == NOW.isoformat()
    assert requests[0].url.host == "91.push2.eastmoney.com"
    assert requests[0].url.params["secid"] == "90.BK1036" and requests[0].url.params["fltt"] == "1"


@pytest.mark.parametrize(
    "data",
    [{"f57": "BK0001", "f59": 2}, {"f57": "BK1036"}, {"f57": "BK1036", "f59": True}, {"f57": "BK1036", "f59": -1}],
)
async def test_wrong_quote_identity_or_unknown_precision_is_rejected(monkeypatch, data):
    monkeypatch.setattr(client_module, "_request_json", AsyncMock(return_value={"data": data}))
    with pytest.raises(SectorDataUnavailable):
        await fetch_sector_quote(SECTOR)


async def test_invalid_code_cannot_reach_network_even_if_schema_bypassed(monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(client_module, "_request_json", request)
    item = SectorItem.model_construct(sector_code="https://private.example", name="fake", sector_type="industry")
    with pytest.raises(ValueError):
        await fetch_sector_quote(item)
    request.assert_not_called()


async def test_network_failure_uses_bounded_same_provider_backup(monkeypatch):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if len(hosts) == 1:
            raise httpx.ConnectError("upstream disconnect", request=request)
        return httpx.Response(200, json={"rc": 0, "data": {"total": 1, "diff": [{"f12": "BK1036", "f14": "半导体"}]}})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    rows = await fetch_sector_catalog("industry")
    assert len(rows) == 1 and hosts == ["79.push2.eastmoney.com", "push2.eastmoney.com"]


@pytest.fixture
def sectors(monkeypatch):
    cache = InMemoryCacheService()
    catalog = AsyncMock(side_effect=lambda kind: [SECTOR] if kind == "industry" else [CONCEPT])
    fetch = AsyncMock(return_value=quote())
    monkeypatch.setattr(service_module, "cache_service", cache)
    monkeypatch.setattr(service_module, "fetch_sector_catalog", catalog)
    monkeypatch.setattr(service_module, "fetch_sector_quote", fetch)
    monkeypatch.setattr(service_module, "business_now", lambda: NOW)
    monkeypatch.setattr(service_module, "utc_now", lambda: NOW.astimezone(UTC).replace(tzinfo=None))
    monkeypatch.setattr(service_module.fund_service, "get_sector_evidence", AsyncMock(return_value=evidence()))
    return SimpleNamespace(service=SectorService(), fetch=fetch, catalog=catalog, cache=cache)


async def test_live_default_bypasses_quote_cache_but_reuses_complete_catalog(sectors):
    request = SectorMarketRequest(keyword="BK1036")
    first = await sectors.service.market(request)
    await sectors.service.market(request)
    assert sectors.fetch.await_count == 2 and sectors.catalog.await_count == 2
    assert first.sectors[0].change_pct == -1.11 and not first.sectors[0].stale
    assert first.sectors[0].quote_time != first.sectors[0].fetched_at


async def test_success_cache_keeps_source_time_and_expires(sectors, monkeypatch):
    request = SectorMarketRequest(keyword="BK1036", refresh=False)
    await sectors.service.market(request)
    second = await sectors.service.market(request)
    assert sectors.fetch.await_count == 1 and second.sectors[0].from_cache
    later = NOW + timedelta(seconds=16)
    monkeypatch.setattr(service_module, "utc_now", lambda: later.astimezone(UTC).replace(tzinfo=None))
    await sectors.service.market(request)
    assert sectors.fetch.await_count == 2


async def test_cached_quote_is_refetched_when_business_date_changes(sectors, monkeypatch):
    request = SectorMarketRequest(keyword="BK1036", refresh=False)
    await sectors.service.market(request)
    monkeypatch.setattr(service_module, "business_now", lambda: NOW + timedelta(days=1))
    result = await sectors.service.market(request)
    assert sectors.fetch.await_count == 2 and result.sectors[0].stale


@pytest.mark.parametrize(
    "changes", [{"quote_time": "2026-10-08T15:00:00+08:00"}, {"quote_time": None}, {"price": 0}, {"change_pct": None}]
)
async def test_invalid_stale_or_incomplete_quotes_are_never_cached(sectors, changes):
    sectors.fetch.return_value = quote(**changes)
    request = SectorMarketRequest(keyword="BK1036", refresh=False)
    first = await sectors.service.market(request)
    await sectors.service.market(request)
    assert sectors.fetch.await_count == 2
    if "quote_time" in changes:
        assert first.sectors[0].stale
    if "price" in changes:
        assert first.sectors[0].price is None and first.sectors[0].error_code
    if "change_pct" in changes:
        assert first.sectors[0].change_pct is None


async def test_partial_catalog_outage_is_explicit_and_failure_is_retried_next_query(sectors):
    async def failing(kind):
        if kind == "concept":
            raise httpx.ConnectError("private detail")
        return [SECTOR]

    sectors.catalog.side_effect = failing
    first = await sectors.service.market(SectorMarketRequest(keyword="BK1036"))
    second = await sectors.service.market(SectorMarketRequest(keyword="missing"))
    assert first.unavailable_catalogs == ["concept"] and first.sectors[0].price is not None
    assert not second.sectors and second.unavailable_catalogs == ["concept"]
    assert sectors.catalog.await_count == 3


async def test_cache_outage_does_not_prevent_live_quotes(sectors, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "cache_service",
        SimpleNamespace(get=AsyncMock(side_effect=RuntimeError()), set=AsyncMock(side_effect=RuntimeError())),
    )
    result = await sectors.service.market(SectorMarketRequest(keyword="BK1036", refresh=False))
    assert result.sectors[0].price == 2503.39


async def test_tool_contracts_unknown_fund_missing_board_and_upstream_safe_errors(sectors, monkeypatch):
    monkeypatch.setattr(fund_tool_module, "sector_service", sectors.service)
    monkeypatch.setattr(market_tool_module, "sector_service", sectors.service)
    invalid = await get_fund_sectors.ainvoke({"fund_code": "12345"})
    assert invalid.startswith("[TOOL_ERROR] INVALID_ARGUMENT")
    text = await get_fund_sectors.ainvoke({"fund_code": "012345"})
    data = json.loads(text.splitlines()[1])
    assert data["sectors"][0]["evidence_type"] == "disclosed_industry"
    assert "as_of=2026-06-30" in text
    assert (await get_sector_market.ainvoke({"keyword": "missing"})).startswith("[TOOL_ERROR] SECTOR_NOT_FOUND")
    assert (await get_sector_market.ainvoke({"keyword": " "})).startswith("[TOOL_ERROR] INVALID_ARGUMENT")
    sectors.fetch.side_effect = RuntimeError("private detail")
    failed = await get_sector_market.ainvoke({"keyword": "BK1036"})
    assert failed.startswith("[TOOL_ERROR] DATA_NOT_AVAILABLE") and "private detail" not in failed
    service_module.fund_service.get_sector_evidence.return_value = None
    assert (await get_fund_sectors.ainvoke({"fund_code": "012345"})).startswith("[TOOL_ERROR] DATA_NOT_AVAILABLE")


async def test_metadata_query_does_not_fetch_nav_or_stock_quotes(monkeypatch):
    service = FundService()
    monkeypatch.setattr(
        fund_module.fund_repository,
        "get_fund",
        AsyncMock(return_value=SimpleNamespace(fund_name="测试基金", fund_type="混合")),
    )
    industries = [FundIndustryItem(industry="半导体", weight=40)]
    monkeypatch.setattr(service, "_industry_allocation", AsyncMock(return_value=(industries, date(2026, 6, 30))))
    monkeypatch.setattr(service, "get_holdings", AsyncMock(side_effect=AssertionError("不要获取股票报价")))
    result = await service.get_sector_evidence("012345")
    assert result.fund_name == "测试基金" and result.industries == industries
    service.get_holdings.assert_not_called()


async def test_industry_cache_failure_preserves_name_evidence(monkeypatch):
    service = FundService()
    monkeypatch.setattr(
        fund_module.fund_repository,
        "get_fund",
        AsyncMock(return_value=SimpleNamespace(fund_name="测试半导体混合", fund_type="混合")),
    )
    monkeypatch.setattr(service, "_industry_allocation", AsyncMock(side_effect=RuntimeError("cache failure")))
    result = await service.get_sector_evidence("012345")
    assert result is not None and not result.industries
    links = match_fund_sectors(result, [SECTOR], 5)
    assert links.sectors[0].evidence_type == "fund_name_hint" and links.report_date is None


def test_registry_and_parameter_bounds():
    assert TOOLS_VERSION == "v17" and get_fund_sectors in FUND_TOOLS and get_sector_market in FUND_TOOLS
    assert get_sector_market in DEFAULT_AGENT_TOOLS
    assert set(get_fund_sectors.args) == {"fund_code", "limit"}
    assert set(get_sector_market.args) == {"keyword", "sector_type", "limit", "refresh"}
    for args in [{"keyword": "a", "limit": 6}, {"keyword": "a", "sector_type": "global"}, {"keyword": "a" * 65}]:
        with pytest.raises(ValidationError):
            SectorMarketRequest(**args)


@pytest.mark.parametrize("stream", [False, True])
async def test_agent_chains_fund_to_board_and_can_refresh_across_turns(sectors, monkeypatch, stream):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(fund_tool_module, "sector_service", sectors.service)
    monkeypatch.setattr(market_tool_module, "sector_service", sectors.service)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)

    class ScriptedLLM:
        calls = 0

        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            latest = next(message for message in reversed(inputs) if message.type != "system")
            if latest.type == "tool" and latest.name == "get_sector_market":
                assert latest.content.startswith("[TOOL_OK]") and '"change_pct":-1.11' in latest.content
                return AIMessage(content="基金披露关联半导体板块，板块最新涨跌幅-1.11%；不等于基金收益。")
            self.calls += 1
            if latest.type == "tool":
                payload = json.loads(latest.content.splitlines()[1])
                name, arguments = "get_sector_market", {"keyword": payload["sectors"][0]["sector_code"]}
            else:
                name, arguments = "get_fund_sectors", {"fund_code": "012345"}
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": arguments, "id": f"sector-{self.calls}", "type": "tool_call"}],
            )

    monkeypatch.setattr(agent, "llm_service", ScriptedLLM())
    # 三个新用户轮均串联两工具，历史调用不能误触重复拦截。
    for _ in range(3):
        messages = [Message(role="user", content="查询基金关联板块涨跌")]
        if stream:
            async for _ in agent.get_stream_response(messages, "sector-test", user_id="42"):
                pass
            response = await agent.get_chat_history("sector-test")
        else:
            response = await agent.get_response(messages, "sector-test", user_id="42")
        assert response[-1].role == "assistant"
    assert sectors.fetch.await_count == 3


async def test_same_turn_repeated_sector_query_is_bounded(sectors, monkeypatch):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    monkeypatch.setattr(market_tool_module, "sector_service", sectors.service)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)

    class RepeatingLLM:
        count = 0

        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            latest = next(message for message in reversed(inputs) if message.type != "system")
            if latest.type == "tool" and "DUPLICATE_TOOL_CALL" in latest.content:
                return AIMessage(content="本轮已查询板块行情，使用已有结果。")
            self.count += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_sector_market",
                        "args": {"keyword": "BK1036"},
                        "id": f"loop-{self.count}",
                        "type": "tool_call",
                    }
                ],
            )

    monkeypatch.setattr(agent, "llm_service", RepeatingLLM())
    response = await agent.get_response([Message(role="user", content="查看半导体板块")], "sector-loop", user_id="42")
    assert response[-1].role == "assistant" and sectors.fetch.await_count == 2
