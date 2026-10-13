"""分析候选使用全名册相似度匹配，不受连续子串、别名重复或持仓限制."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import funds as funds_api
from app.api.v1.auth import get_current_identity
from app.core.cache import InMemoryCacheService, cache_key
from app.core.limiter import limiter
from app.models.fund import Fund, FundNav
from app.services import fund_service as fund_service_module
from app.services.fund_service import FundService

DIRECTORY = [
    ("000009", "平安医疗健康混合A"),
    ("000005", "平安科技创新3年封闭运作混合A"),
    ("000001", "平安科技创新混合A"),
    ("000001", "平安科技创新混合型证券投资基金A"),
    ("000002", "平安科技创新混合C"),
    ("000003", "平安科技创新混合E"),
    ("000008", "其他债券基金"),
]


@pytest.fixture
def reader(monkeypatch):
    service = FundService()
    service.name_directory = AsyncMock(return_value=DIRECTORY)
    service._search_fund_rows = AsyncMock(side_effect=AssertionError("name candidates must not use substring search"))
    service._user_flag_sets = AsyncMock(side_effect=AssertionError("public candidates must not require holdings"))
    service._backfill_navs = AsyncMock(side_effect=AssertionError("do not fetch NAV for unselected candidates"))
    return service


@pytest.mark.parametrize("query", ["平安科技混合", "平安 科技 混合型", "平安科技"])
async def test_missing_middle_words_are_ranked_and_aliases_deduplicated_before_top_three(reader, query):
    # 不包含连续的“平安科技混合”，但仍应找到“平安科技创新混合”。
    if "混合" in query:
        assert query not in DIRECTORY[2][1]
    results = await reader.search_analysis_candidates(query)
    assert [item.fund_code for item in results] == ["000001", "000002", "000003"]
    assert len({item.fund_code for item in results}) == 3
    reader._search_fund_rows.assert_not_awaited()
    reader._user_flag_sets.assert_not_awaited()
    reader._backfill_navs.assert_not_awaited()


async def test_explicit_share_class_does_not_include_other_classes(reader):
    results = await reader.search_analysis_candidates("平安科技混合C")
    assert [item.fund_code for item in results] == ["000002"]


async def test_full_name_exact_match_precedes_shorter_alias_and_other_candidates(reader):
    query = "平安科技创新混合型证券投资基金A"
    results = await reader.search_analysis_candidates(query)
    assert results[0].fund_code == "000001" and results[0].fund_name == query


async def test_no_relevant_candidates_returns_empty_instead_of_unrelated_top_three(reader):
    assert await reader.search_analysis_candidates("不存在的基金") == []
    assert await reader.search_analysis_candidates("  ") == []


async def test_six_digit_code_is_exact_and_uses_no_directory(reader):
    reader._search_fund_rows = AsyncMock(
        return_value=[
            Fund(fund_code="000001", fund_name="精确基金"),
            Fund(fund_code="000002", fund_name="其他基金"),
        ]
    )
    results = await reader.search_analysis_candidates("000001")
    assert [item.fund_code for item in results] == ["000001"]
    reader.name_directory.assert_not_awaited()
    assert await reader.search_analysis_candidates("000009") == []


async def test_catalog_failure_is_not_reported_as_no_match(reader):
    reader.name_directory.side_effect = TimeoutError("catalog unavailable")
    with pytest.raises(TimeoutError):
        await reader.search_analysis_candidates("平安科技混合")


@pytest.fixture
def public_search(monkeypatch):
    service = FundService()
    catalog = {code: Fund(fund_code=code, fund_name=name, fund_type="混合型") for code, name in DIRECTORY}
    navs = {
        code: FundNav(fund_code=code, nav_date=date(2026, 10, 9), unit_nav=1.2, daily_return=0.8) for code in catalog
    }
    cache = InMemoryCacheService()
    substring = AsyncMock(return_value=[])
    by_codes = AsyncMock(side_effect=lambda codes: {code: catalog[code] for code in codes if code in catalog})

    async def register(record):
        catalog[record.fund_code] = Fund(fund_code=record.fund_code, fund_name=record.fund_name)

    writes = AsyncMock(side_effect=register)
    monkeypatch.setattr(fund_service_module, "cache_service", cache)
    monkeypatch.setattr(fund_service_module, "AKSHARE_AVAILABLE", False)
    monkeypatch.setattr(fund_service_module.fund_repository, "search_funds", substring)
    monkeypatch.setattr(fund_service_module.fund_repository, "get_funds", by_codes)
    monkeypatch.setattr(fund_service_module.fund_repository, "get_latest_navs", AsyncMock(return_value=navs))
    monkeypatch.setattr(fund_service_module.fund_write_repository, "upsert_fund_from_record", writes)
    service.name_directory = AsyncMock(return_value=DIRECTORY)
    service._user_flag_sets = AsyncMock(
        side_effect=lambda user_id: ({"000001"}, {"000002"}) if user_id == 42 else (set(), set())
    )
    service._backfill_navs = AsyncMock(return_value=navs)
    return SimpleNamespace(
        service=service, catalog=catalog, navs=navs, cache=cache, substring=substring, by_codes=by_codes, writes=writes
    )


async def test_public_search_uses_same_fuzzy_top_three_with_nav_and_fresh_user_flags(public_search):
    scenario = public_search
    results = await scenario.service.search("平安科技混合", 42)
    candidates = await scenario.service.search_analysis_candidates("平安科技混合")
    assert [item.fund_code for item in results] == [item.fund_code for item in candidates]
    assert [item.fund_code for item in results] == ["000001", "000002", "000003"]
    # 展示简称不能覆盖已有正式名称；净值和用户标记仍来自原搜索链路。
    assert results[0].fund_name == "平安科技创新混合型证券投资基金A"
    assert all(item.latest_nav == 1.2 and item.daily_return == 0.8 for item in results)
    assert results[0].is_watchlisted and results[1].is_held
    other_user = await scenario.service.search("平安科技混合", 99)
    assert all(not item.is_watchlisted and not item.is_held for item in other_user)
    scenario.substring.assert_awaited_once()
    scenario.writes.assert_not_awaited()
    scenario.service._backfill_navs.assert_not_awaited()


async def test_fuzzy_search_registers_only_missing_codes_and_backfills_missing_nav(public_search):
    scenario = public_search
    del scenario.catalog["000002"]
    del scenario.navs["000002"]
    results = await scenario.service.search("平安科技混合", 42)
    assert [item.fund_code for item in results] == ["000001", "000002", "000003"]
    assert results[1].fund_name == "平安科技创新混合C"
    scenario.writes.assert_awaited_once()
    assert scenario.writes.await_args.args[0].fund_code == "000002"
    scenario.service._backfill_navs.assert_awaited_once_with(["000002"], ["000001", "000002", "000003"])


async def test_existing_substring_results_keep_broad_search_behavior(public_search):
    scenario = public_search
    scenario.substring.return_value = list(scenario.catalog.values())
    results = await scenario.service.search("平安", 42)
    assert len(results) > 3
    scenario.service.name_directory.assert_not_awaited()
    scenario.by_codes.assert_not_awaited()
    scenario.writes.assert_not_awaited()


@pytest.mark.parametrize("keyword", ["000001", "000", "  "])
async def test_code_search_and_empty_input_do_not_trigger_fuzzy_names(public_search, keyword):
    assert await public_search.service.search(keyword, 42) == []
    public_search.service.name_directory.assert_not_awaited()
    public_search.writes.assert_not_awaited()


async def test_failed_fuzzy_directory_is_not_cached_and_next_query_can_recover(public_search):
    scenario = public_search
    scenario.service.name_directory.side_effect = [TimeoutError("catalog unavailable"), DIRECTORY]
    assert await scenario.service.search("平安科技混合", 42) == []
    assert await scenario.cache.get(cache_key("fund_search", "平安科技混合")) is None
    results = await scenario.service.search("平安科技混合", 42)
    assert [item.fund_code for item in results] == ["000001", "000002", "000003"]


async def test_fund_search_api_reuses_service_fuzzy_matching(public_search, monkeypatch):
    monkeypatch.setattr(funds_api, "fund_service", public_search.service)
    monkeypatch.setattr(limiter, "enabled", False)
    app = FastAPI()
    app.include_router(funds_api.router, prefix="/funds")
    app.dependency_overrides[get_current_identity] = lambda: SimpleNamespace(user_id=42, session_id="search-test")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/funds/search", params={"q": "平安科技混合"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [item["fund_code"] for item in payload["items"]] == ["000001", "000002", "000003"]
    assert payload["items"][0]["latest_nav"] == 1.2
    assert payload["items"][0]["is_watchlisted"]
