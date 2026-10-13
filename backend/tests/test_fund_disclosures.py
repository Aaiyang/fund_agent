"""历任经理、公告索引、分类/时间/身份边界和真实Agent图执行."""

import importlib
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.fund import get_fund_announcements, get_fund_managers
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS, FUND_TOOLS, TOOLS_VERSION
from app.core.cache import InMemoryCacheService
from app.core.config import settings
from app.integrations.fund_data.disclosure_client import (
    FundDisclosureUnavailable,
    fetch_announcements,
    fetch_manager_history,
    parse_announcement_page,
    parse_manager_history,
)
from app.schemas import Message
from app.schemas.fund_disclosure import FundAnnouncementsRequest
from app.services.fund_disclosure_utils import merge_manager_tenures
from app.services.fund_service import FundService

client_module = importlib.import_module("app.integrations.fund_data.disclosure_client")
utils_module = importlib.import_module("app.services.fund_disclosure_utils")
service_module = importlib.import_module("app.services.fund_service")
manager_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_managers")
notice_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_announcements")
STAMP = datetime(2026, 10, 9, 7, 30)


def history_html(code="000001"):
    return f"""<title>测试基金({code})基金经理</title><table></table>
    <table><tr><th>起始期</th><th>截止期</th><th>基金经理</th><th>任职期间</th><th>任职回报</th></tr>
    <tr><td>2025-01-01</td><td>至今</td><td><a href='https://fund.eastmoney.com/manager/111.html'>张甲</a></td><td>1年又281天</td><td>5%</td></tr>
    <tr><td>2024-01-01</td><td>2024-12-31</td><td><a href='/manager/111.html'>张甲</a><a href='//fund.eastmoney.com/manager/222.html'>李乙</a></td><td>366天</td><td>3%</td></tr>
    <tr><td>2022-01-01</td><td>2022-12-31</td><td><a href='/manager/111.html'>张甲</a></td><td>365天</td><td>2%</td></tr></table>
    <table><tr><th>基金代码</th><th>基金名称</th><th>基金类型</th><th>起始时间</th><th>截止时间</th></tr>
    <tr><td>999999</td><td>其他基金</td><td>混合</td><td>2000-01-01</td><td>至今</td></tr></table>"""


def notice(title="测试基金2026年中期报告", **changes):
    return {
        "FUNDCODE": "000001",
        "TITLE": title,
        "ID": "AN202609011234567890",
        "PUBLISHDATE": "2026-09-01T00:00:00",
        "NEWCATEGORY": "3",
        **changes,
    }


def page_payload(rows=None, **changes):
    rows = rows if rows is not None else [notice()]
    return {"ErrCode": 0, "TotalCount": len(rows), "Data": rows, "PageIndex": 1, "PageSize": 50, **changes}


def test_manager_periods_retain_joint_names_and_ignore_other_funds():
    result = parse_manager_history(history_html(), "000001")
    assert len(result.periods) == 3 and result.periods[0].is_current
    assert result.periods[0].end_date is None and result.periods[0].start_date == date(2025, 1, 1)
    assert [item.name for item in result.periods[1].managers] == ["张甲", "李乙"]
    assert not any(period.start_date == date(2000, 1, 1) for period in result.periods)


def test_personal_tenures_merge_contiguous_management_but_preserve_reappointments():
    result = merge_manager_tenures(parse_manager_history(history_html(), "000001").periods)
    rows = [row for row in result if row.manager.manager_id == "111"]
    assert len(rows) == 2 and rows[0].start_date == date(2024, 1, 1) and rows[0].is_current
    assert rows[1].start_date == date(2022, 1, 1) and rows[1].end_date == date(2022, 12, 31)


def test_same_name_different_manager_ids_never_merge():
    data = parse_manager_history(history_html().replace("李乙", "张甲"), "000001")
    result = merge_manager_tenures(data.periods)
    assert {row.manager.manager_id for row in result} == {"111", "222"}


@pytest.mark.parametrize(
    "html",
    [
        history_html("000002"),
        history_html().replace("起始期", "unknown"),
        history_html().replace("2024-12-31", "2023-12-31"),
        history_html().replace("至今", "--"),
        history_html().replace("/manager/111.html", "/other/111.html"),
    ],
)
def test_unknown_structure_identity_or_dates_cannot_become_empty_history(html):
    with pytest.raises(FundDisclosureUnavailable):
        parse_manager_history(html, "000001")


def test_notice_source_date_link_and_category_are_truthful():
    result = parse_announcement_page(page_payload(), "000001", 1, 50)
    item = result.items[0]
    assert item.published_date == date(2026, 9, 1) and item.category == "reports"
    assert item.url == "https://fund.eastmoney.com/gonggao/000001,AN202609011234567890.html"
    assert not item.major_change_hints


@pytest.mark.parametrize(
    ("title", "hint"),
    [
        ("关于变更基金经理的公告", "manager_change"),
        ("基金合同修订的公告", "contract_change"),
        ("基金清算报告", "termination_or_liquidation"),
        ("调整本基金管理费率的公告", "fee_change"),
        ("暂停大额申购的公告", "subscription_redemption_change"),
        ("本基金投资范围调整的公告", "investment_scope_change"),
    ],
)
def test_major_change_hints_are_explicit_title_rules(title, hint):
    result = parse_announcement_page(page_payload([notice(title)]), "000001", 1, 50)
    assert hint in result.items[0].major_change_hints


def test_sales_termination_does_not_mean_fund_contract_termination():
    result = parse_announcement_page(
        page_payload([notice("关于终止某销售公司办理旗下基金销售业务的公告", NEWCATEGORY="5")]), "000001", 1, 50
    )
    assert result.items[0].category == "sales" and not result.items[0].major_change_hints


@pytest.mark.parametrize(
    "changes",
    [{"ErrCode": 1}, {"PageIndex": 2}, {"PageSize": 100}, {"TotalCount": -1}, {"TotalCount": 100, "Data": []}],
)
def test_upstream_error_and_missing_page_never_mean_no_notices(changes):
    with pytest.raises(FundDisclosureUnavailable):
        parse_announcement_page(page_payload(**changes), "000001", 1, 50)


def test_cross_fund_rows_are_rejected_and_invalid_urls_are_not_returned():
    with pytest.raises(FundDisclosureUnavailable):
        parse_announcement_page(page_payload([notice(FUNDCODE="000002")]), "000001", 1, 50)
    result = parse_announcement_page(
        page_payload([notice(ID="https://private.example"), notice(PUBLISHDATE="missing", NEWCATEGORY="999")]),
        "000001",
        1,
        50,
    )
    assert (
        result.invalid_items == 1 and result.items[0].published_date is None and result.items[0].category == "unknown"
    )


async def test_network_contract_is_fixed_code_scoped_and_bounded(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith(".html"):
            return httpx.Response(200, text=history_html())
        return httpx.Response(200, json=page_payload())

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    managers = await fetch_manager_history("000001")
    notices = await fetch_announcements("000001", 3, 1, 50)
    assert len(managers.periods) == 3 and len(notices.items) == 1
    assert requests[0].url.path == "/jjjl_000001.html"
    assert requests[1].url.host == "api.fund.eastmoney.com" and requests[1].url.params["fundcode"] == "000001"
    assert requests[1].url.params["type"] == "3" and requests[1].url.params["pageSize"] == "50"


@pytest.mark.parametrize("code", ["https://internal", "12345", "000001/../", "０００００１"])
async def test_adapter_rejects_non_code_before_network(monkeypatch, code):
    fetch = AsyncMock()
    monkeypatch.setattr(client_module, "_get", fetch)
    with pytest.raises(ValueError):
        await fetch_manager_history(code)
    with pytest.raises(ValueError):
        await fetch_announcements(code, 0, 1, 50)
    fetch.assert_not_called()


@pytest.fixture
def disclosures(monkeypatch):
    cache = InMemoryCacheService()
    history = AsyncMock(return_value=parse_manager_history(history_html(), "000001"))
    notices = AsyncMock(return_value=parse_announcement_page(page_payload(), "000001", 1, 50))
    monkeypatch.setattr(utils_module, "cache_service", cache)
    monkeypatch.setattr(utils_module, "utc_now", lambda: STAMP)
    monkeypatch.setattr(service_module.akshare_fund_provider, "get_manager_history", history)
    monkeypatch.setattr(service_module.akshare_fund_provider, "get_announcements", notices)
    service = FundService()
    monkeypatch.setattr(manager_tool_module, "fund_service", service)
    monkeypatch.setattr(notice_tool_module, "fund_service", service)
    return SimpleNamespace(service=service, history=history, notices=notices, cache=cache)


async def test_history_cache_refresh_expiration_and_truncation(disclosures, monkeypatch):
    first = await disclosures.service.get_managers("000001", limit=1)
    cached = await disclosures.service.get_managers("000001")
    assert first.truncated and first.total_periods == 3 and first.total_tenures == 3
    assert cached.from_cache and cached.fetched_at == STAMP and disclosures.history.await_count == 1
    await disclosures.service.get_managers("000001", refresh=True)
    monkeypatch.setattr(utils_module, "utc_now", lambda: STAMP + timedelta(hours=2))
    await disclosures.service.get_managers("000001")
    assert disclosures.history.await_count == 3


async def test_announcement_category_page_and_cache_are_isolated(disclosures):
    await disclosures.service.get_announcements(FundAnnouncementsRequest(fund_code="000001", category="reports"))
    cached = await disclosures.service.get_announcements(
        FundAnnouncementsRequest(fund_code="000001", category="reports")
    )
    assert cached.from_cache and disclosures.notices.await_count == 1
    await disclosures.service.get_announcements(FundAnnouncementsRequest(fund_code="000001", category="all"))
    assert disclosures.notices.await_count == 2
    disclosures.notices.assert_awaited_with("000001", 0, 1, 50)


async def test_major_change_filter_retains_scan_window_and_continuation(disclosures):
    rows = [notice("基金经理变更公告", NEWCATEGORY="4"), notice("中期报告", ID="AN202609021234567891")]
    disclosures.notices.return_value = parse_announcement_page(page_payload(rows, TotalCount=100), "000001", 1, 50)
    result = await disclosures.service.get_announcements(
        FundAnnouncementsRequest(fund_code="000001", category="major_changes")
    )
    assert len(result.items) == 1 and result.matched_count == 1 and result.scanned_count == 2
    assert result.has_more and result.next_page == 2 and result.upstream_total == 100
    assert not result.content_available and any("待核验" in note for note in result.warnings)


async def test_date_filters_unknown_dates_and_no_match_are_not_absence_claim(disclosures):
    disclosures.notices.return_value = parse_announcement_page(
        page_payload([notice(PUBLISHDATE=None)], TotalCount=100), "000001", 1, 50
    )
    result = await disclosures.service.get_announcements(
        FundAnnouncementsRequest(fund_code="000001", start_date=date(2026, 1, 1))
    )
    assert not result.items and result.has_more and any("未知" in note for note in result.warnings)


async def test_invalid_or_failed_notice_page_is_never_cached(disclosures):
    disclosures.notices.return_value = parse_announcement_page(page_payload([notice(ID="invalid")]), "000001", 1, 50)
    request = FundAnnouncementsRequest(fund_code="000001")
    await disclosures.service.get_announcements(request)
    await disclosures.service.get_announcements(request)
    assert disclosures.notices.await_count == 2
    disclosures.notices.side_effect = httpx.ConnectError("private credential")
    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            await disclosures.service.get_announcements(request)
    assert disclosures.notices.await_count == 4


async def test_cache_failure_does_not_break_online_query(disclosures, monkeypatch):
    monkeypatch.setattr(
        utils_module,
        "cache_service",
        SimpleNamespace(get=AsyncMock(side_effect=RuntimeError()), set=AsyncMock(side_effect=RuntimeError())),
    )
    assert (await disclosures.service.get_managers("000001")).periods
    assert (await disclosures.service.get_announcements(FundAnnouncementsRequest(fund_code="000001"))).items


async def test_missing_records_are_explicit_and_partial_page_is_not_cached(disclosures):
    disclosures.notices.return_value = parse_announcement_page(page_payload(TotalCount=100), "000001", 1, 50)
    request = FundAnnouncementsRequest(fund_code="000001")
    first = await disclosures.service.get_announcements(request)
    await disclosures.service.get_announcements(request)
    assert first.scanned_count == 1 and first.missing_items == 49
    assert disclosures.notices.await_count == 2 and any("缺失" in note for note in first.warnings)


async def test_tools_use_safe_errors_and_correct_dates(disclosures):
    assert (await get_fund_managers.ainvoke({"fund_code": "12345"})).startswith("[TOOL_ERROR] INVALID_ARGUMENT")
    invalid = await get_fund_announcements.ainvoke(
        {"fund_code": "000001", "start_date": "2026-10-10", "end_date": "2026-10-09"}
    )
    assert invalid.startswith("[TOOL_ERROR] INVALID_ARGUMENT")
    text = await get_fund_managers.ainvoke({"fund_code": "000001"})
    assert text.startswith("[TOOL_OK]") and "as_of=" not in text
    text = await get_fund_announcements.ainvoke({"fund_code": "000001"})
    assert "as_of=2026-09-01" in text and json.loads(text.splitlines()[1])["content_available"] is False
    disclosures.history.side_effect = RuntimeError("private credential")
    failed = await get_fund_managers.ainvoke({"fund_code": "000001", "refresh": True})
    assert failed.startswith("[TOOL_ERROR] UPSTREAM_ERROR") and "private credential" not in failed


def test_registry_and_request_scope():
    assert TOOLS_VERSION == "v17"
    assert get_fund_managers in FUND_TOOLS and get_fund_announcements in DEFAULT_AGENT_TOOLS
    assert set(get_fund_managers.args) == {"fund_code", "limit", "refresh"}
    assert "user_id" not in get_fund_announcements.args and "url" not in get_fund_announcements.args
    for changes in [{"page": 1001}, {"limit": 51}, {"category": "private"}]:
        with pytest.raises(ValidationError):
            FundAnnouncementsRequest(fund_code="000001", **changes)


@pytest.mark.parametrize("stream", [False, True])
async def test_agent_queries_both_tools_over_three_new_turns(disclosures, monkeypatch, stream):
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
                if latest.name == "get_fund_announcements":
                    return AIMessage(content="已取得历任经理日期和公告索引；报告正文尚未读取。")
                name = "get_fund_announcements"
            else:
                name = "get_fund_managers"
            self.count += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": name,
                        "args": {"fund_code": "000001", "refresh": True},
                        "id": f"disclosure-{self.count}",
                        "type": "tool_call",
                    }
                ],
            )

    monkeypatch.setattr(agent, "llm_service", ScriptedLLM())
    for _ in range(3):
        messages = [Message(role="user", content="查看000001历任经理和报告")]
        if stream:
            async for _ in agent.get_stream_response(messages, "disclosure-test", user_id="42"):
                pass
            response = await agent.get_chat_history("disclosure-test")
        else:
            response = await agent.get_response(messages, "disclosure-test", user_id="42")
        assert response[-1].role == "assistant"
    assert disclosures.history.await_count == 3 and disclosures.notices.await_count == 3
