"""在线日历契约：假期/调休、跨年、失败回退、源数据校验与工具调用."""

import importlib
import json
from datetime import date, timedelta

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from tenacity import wait_none

from app.agent.context.budget import token_estimator
from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.get_calendar import get_calendar
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, TOOLS_VERSION
from app.core.cache import InMemoryCacheService, cache_key
from app.core.config import settings
from app.integrations.holiday_calendar import CalendarDataUnavailable, TimorHolidayProvider, parse_year_payload
from app.schemas import Message
from app.schemas.calendar import HolidayYear
from app.services import calendar_service as calendar_module
from app.services.calendar_service import CalendarService, build_calendar_request
from app.utils.clock import utc_now


def payload(year: int = 2026) -> dict:
    return {
        "code": 0,
        "holiday": {
            "01-01": {"holiday": True, "name": "元旦", "date": f"{year}-01-01"},
            "10-01": {"holiday": True, "name": "国庆节", "date": f"{year}-10-01"},
            "10-02": {"holiday": True, "name": "国庆节", "date": f"{year}-10-02"},
            "10-10": {"holiday": False, "name": "国庆节后补班", "target": "国庆节", "date": f"{year}-10-10"},
        },
    }


class FakeProvider:
    def __init__(self):
        self.calls: list[int] = []
        self.error: Exception | None = None

    async def get_year(self, year: int) -> HolidayYear:
        self.calls.append(year)
        if self.error:
            raise self.error
        return parse_year_payload(payload(year), year, f"https://fixture.example/year/{year}/")


@pytest.fixture
def calendar(monkeypatch):
    provider = FakeProvider()
    cache = InMemoryCacheService()
    service = CalendarService(provider)
    monkeypatch.setattr(calendar_module, "cache_service", cache)
    monkeypatch.setattr(importlib.import_module("app.agent.tools.get_calendar"), "calendar_service", service)
    return service, provider, cache


def data(text: str) -> dict:
    assert text.startswith("[TOOL_OK]")
    return json.loads(text.split("\n")[1])


@pytest.mark.parametrize(
    ("day", "kind", "working", "weekend"),
    [
        ("2026-10-01", "holiday", False, False),
        ("2026-10-10", "makeup_workday", True, True),
        ("2026-10-11", "weekend", False, True),
        ("2026-10-12", "workday", True, False),
    ],
)
async def test_day_types(calendar, day, kind, working, weekend):
    text = await get_calendar.ainvoke({"start_date": day})
    result = data(text)
    assert result["days"][0]["kind"] == kind
    assert result["days"][0]["is_workday"] is working
    assert result["days"][0]["is_weekend"] is weekend
    assert "证券交易日历" in text
    assert result["sources"] and result["fetched_at_utc"]
    assert result["cache_used"] is False
    assert calendar[1].calls == [2026]


async def test_default_date_uses_business_clock(calendar, monkeypatch):
    monkeypatch.setattr(calendar_module, "business_today", lambda: date(2026, 10, 10))
    result = data(await get_calendar.ainvoke({}))
    assert result["start_date"] == result["end_date"] == "2026-10-10"
    assert result["days"][0]["kind"] == "makeup_workday"


async def test_range_and_cross_year(calendar):
    result = data(await get_calendar.ainvoke({"start_date": "2026-12-30", "end_date": "2027-01-02"}))
    assert [day["date"] for day in result["days"]] == ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]
    assert result["days"][2]["kind"] == "holiday"
    assert sorted(calendar[1].calls) == [2026, 2027]
    assert len(result["sources"]) == 2


async def test_year_only_lists_special_days(calendar):
    text = await get_calendar.ainvoke({"year": 2026})
    result = data(text)
    assert result["mode"] == "year" and len(result["days"]) == 4
    assert result["days"][-1]["kind"] == "makeup_workday"
    assert "不列普通工作日" in text
    assert token_estimator.count_text(text) < settings.TOOL_MESSAGE_HARD_LIMIT_TOKENS


@pytest.mark.parametrize(
    "arguments",
    [
        {"start_date": "20261010"},
        {"start_date": "2026-02-30"},
        {"start_date": "2026-10-10", "end_date": "2026-10-01"},
        {"start_date": "2026-01-01", "end_date": "2026-02-01"},
        {"end_date": "2026-10-10"},
        {"year": 2026, "start_date": "2026-10-10"},
        {"year": 1999},
        {"year": 2101},
    ],
)
async def test_invalid_arguments_do_not_call_provider(calendar, arguments):
    text = await get_calendar.ainvoke(arguments)
    assert text.startswith("[TOOL_ERROR] INVALID_ARGUMENT")
    assert calendar[1].calls == []


def test_maximum_range_is_31_days():
    request = build_calendar_request("2026-01-01", "2026-01-31")
    assert (request.end_date - request.start_date).days == 30


async def test_default_refresh_bypasses_cache_but_optional_cache_is_fresh(calendar):
    await get_calendar.ainvoke({"start_date": "2026-10-10"})
    second = data(await get_calendar.ainvoke({"start_date": "2026-10-10"}))
    assert second["cache_used"] is False and calendar[1].calls == [2026, 2026]
    third = data(await get_calendar.ainvoke({"start_date": "2026-10-10", "refresh": False}))
    assert third["cache_used"] is True and calendar[1].calls == [2026, 2026]


async def test_refresh_failure_returns_original_timestamp_and_explicit_stale(calendar):
    original = data(await get_calendar.ainvoke({"start_date": "2026-10-10"}))
    calendar[1].error = httpx.ConnectError("unavailable")
    text = await get_calendar.ainvoke({"start_date": "2026-10-10"})
    result = data(text)
    assert result["fetched_at_utc"] == original["fetched_at_utc"]
    assert result["cache_used"] is True
    assert "stale=true" in text and "未经实时更新" in text


async def test_expired_or_bad_cache_cannot_fabricate_workday(calendar, monkeypatch):
    service, provider, cache = calendar
    snapshot, _, _ = await service._get_year(2026, True)
    provider.error = RuntimeError("unavailable")
    monkeypatch.setattr(calendar_module, "utc_now", lambda: snapshot.fetched_at + timedelta(hours=7))
    text = await get_calendar.ainvoke({"start_date": "2026-10-10"})
    assert text.startswith("[TOOL_ERROR] UPSTREAM_ERROR")
    key = cache_key("calendar:timor:v1", settings.HOLIDAY_API_BASE_URL, "2026")
    await cache.set(
        key, json.dumps({"year": 2026, "records": [], "fetched_at": utc_now().isoformat(), "source": "fixture"})
    )
    assert (await get_calendar.ainvoke({"start_date": "2026-10-10"})).startswith("[TOOL_ERROR] UPSTREAM_ERROR")


async def test_unavailable_year_is_not_cached_and_not_guessed(calendar):
    calendar[1].error = CalendarDataUnavailable("2027 年节假日安排尚未公布或数据源尚未提供")
    text = await get_calendar.ainvoke({"year": 2027})
    assert text.startswith("[TOOL_ERROR] DATA_NOT_AVAILABLE")
    assert calendar[2]._cache == {}


async def test_failed_upstream_has_safe_error_and_no_cache(calendar):
    calendar[1].error = RuntimeError("private credential=example")
    text = await get_calendar.ainvoke({"start_date": "2026-10-10"})
    assert text.startswith("[TOOL_ERROR] UPSTREAM_ERROR")
    assert "credential" not in text and calendar[2]._cache == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"code": -1, "holiday": {}},
        {"code": False, "holiday": {}},
        {"code": 0, "holiday": []},
        {"code": 0, "holiday": {"10-01": {"holiday": "false", "name": "假期", "date": "2026-10-01"}}},
        {"code": 0, "holiday": {"10-01": {"holiday": True, "name": "假期", "date": "2027-10-01"}}},
        {"code": 0, "holiday": {"10-02": {"holiday": True, "name": "假期", "date": "2026-10-01"}}},
    ],
)
def test_bad_provider_payload_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_year_payload(bad, 2026, "https://fixture.example")


def test_empty_or_partial_year_is_unavailable():
    with pytest.raises(CalendarDataUnavailable):
        parse_year_payload({"code": 0, "holiday": {}}, 2027, "https://fixture.example")
    with pytest.raises(CalendarDataUnavailable):
        parse_year_payload({"code": 0, "holiday": {"01-01": payload()["holiday"]["01-01"]}}, 2026, "fixture")


@pytest.mark.parametrize(("first_status", "expected_calls"), [(429, 2), (503, 2), (400, 1)])
async def test_provider_retries_only_transient_http_errors(monkeypatch, first_status, expected_calls):
    module = importlib.import_module("app.integrations.holiday_calendar")
    client = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(first_status, json={"error": "fixture"})
        return httpx.Response(200, json=payload())

    def make_client(**kwargs):
        return client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", make_client)
    # tenacity 在包装函数上动态附加 retry，使用 getattr 保持静态类型检查兼容。
    monkeypatch.setattr(getattr(TimorHolidayProvider.get_year, "retry"), "wait", wait_none())  # noqa: B009
    provider = TimorHolidayProvider()
    if first_status == 400:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.get_year(2026)
    else:
        snapshot = await provider.get_year(2026)
        assert len(snapshot.records) == 4
    assert len(calls) == expected_calls
    assert all(url.endswith("/year/2026/") for url in calls)


def test_tool_registered_without_identity_or_url_arguments():
    assert get_calendar in DEFAULT_AGENT_TOOLS and TOOLS_VERSION == "v20"
    assert set(get_calendar.args) == {"start_date", "end_date", "year", "refresh"}


async def test_calendar_executes_through_real_agent_graph(calendar, monkeypatch):
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    seen = []

    class ScriptedLLM:
        def get_llm(self):
            return None

        async def call(self, inputs, *args, **kwargs):
            seen.append(inputs)
            if len(seen) == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_calendar",
                            "args": {"start_date": "2026-10-10"},
                            "id": "calendar-call",
                            "type": "tool_call",
                        }
                    ],
                )
            result = next(message for message in inputs if message.type == "tool")
            assert '"kind":"makeup_workday"' in result.content
            return AIMessage(content="10月10日是国庆调休补班日，证券开市另需核对交易所公告。")

    monkeypatch.setattr(agent, "llm_service", ScriptedLLM())
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    response = await agent.get_response(
        [Message(role="user", content="10月10日要上班吗？")], "calendar-thread", user_id="42"
    )
    assert response[-1].role == "assistant" and "补班" in response[-1].content
    assert calendar[1].calls == [2026]
