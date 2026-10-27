"""业务工具层的契约测试.

每个工具都对着假的 Service 跑四类情况：成功、参数非法、数据缺失、服务抛错 —— 外加两条
安全不变量：模型能看见的参数 schema 里绝不能出现 user_id，而服务层收到的 user_id
永远来自运行时上下文，绝不是模型自己填的那一个。
"""

import importlib
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.agent.tools import common as tool_common
from app.agent.tools.fund import (
    get_fund_holdings,
    get_fund_history,
    get_fund_snapshot,
    search_funds,
)
from app.agent.tools.market import get_market_context
from app.agent.tools.portfolio import get_portfolio, get_positions
from app.agent.tools.watchlist import get_watchlist
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import (
    ToolRuntimeContext,
    ToolRuntimeError,
    get_tool_runtime,
    runtime_from_config,
    set_tool_runtime,
)
from app.utils.clock import business_today, utc_now

USER = ToolRuntimeContext(user_id=42, thread_id="thread-1", request_id="req-1")


_MODULE_SERVICE_ATTRS = {
    "search_funds": ("app.agent.tools.fund.search_funds", "fund_service"),
    "get_fund_snapshot": ("app.agent.tools.fund.get_fund_snapshot", "fund_service"),
    "get_fund_history": ("app.agent.tools.fund.get_fund_history", "fund_service"),
    "get_fund_holdings": ("app.agent.tools.fund.get_fund_holdings", "fund_service"),
    "get_portfolio": ("app.agent.tools.portfolio.get_portfolio", "portfolio_service"),
    "get_positions": ("app.agent.tools.portfolio.get_positions", "portfolio_service"),
    "get_watchlist": ("app.agent.tools.watchlist.get_watchlist", "watchlist_service"),
    "get_market_context": ("app.agent.tools.market.get_market_context", "market_service"),
}


def _patch_tool_service(monkeypatch, tool_name: str, service) -> None:
    """把补丁打到工具真实模块内部的那个 Service 单例上.

    包的 ``__init__`` 用与子模块同名的方式重新导出了工具对象，所以 monkeypatch 的字符串
    目标会解析到工具本身 —— 必须显式 import 那个模块再改。
    """
    module_path, attr = _MODULE_SERVICE_ATTRS[tool_name]
    monkeypatch.setattr(importlib.import_module(module_path), attr, service)


@pytest.fixture(autouse=True)
def _runtime():
    set_tool_runtime(USER)


# ---------------------------------------------------------------------------
# runtime.py 的用例
# ---------------------------------------------------------------------------


def test_runtime_from_config_parses_identity():
    config = {
        "metadata": {"user_id": "42", "session_id": "s-1"},
        "configurable": {"thread_id": "s-1"},
    }
    context = runtime_from_config(config)
    assert context.user_id == 42
    assert context.thread_id == "s-1"
    assert isinstance(context.request_id, str)


def test_runtime_from_config_rejects_missing_user():
    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime_from_config({"metadata": {}})
    assert excinfo.value.code == "PERMISSION_DENIED"


def test_runtime_contextvar_roundtrip():
    set_tool_runtime(USER)
    assert get_tool_runtime() is USER


# ---------------------------------------------------------------------------
# result.py 的用例
# ---------------------------------------------------------------------------


def test_tool_result_ok_to_text():
    text = ToolResult.ok({"a": 1}, source="svc", as_of="2026-09-30").to_text()
    assert text.startswith("[TOOL_OK]")
    assert '"a":1' in text
    assert "as_of=2026-09-30" in text
    assert "source=svc" in text


def test_tool_result_fail_to_text():
    text = ToolResult.fail("FUND_NOT_FOUND", "未找到基金 005827").to_text()
    assert text.startswith("[TOOL_ERROR] FUND_NOT_FOUND")
    assert "005827" in text


# ---------------------------------------------------------------------------
# search_funds 的用例
# ---------------------------------------------------------------------------


class TestSearchFunds:
    async def test_success_passes_runtime_user_id(self, monkeypatch):
        seen = {}

        async def fake_search(keyword, user_id):
            seen.update(keyword=keyword, user_id=user_id)
            return [SimpleNamespace(fund_code="005827", fund_name="易方达蓝筹精选", fund_type="混合型")]

        _patch_tool_service(monkeypatch, "search_funds", SimpleNamespace(search=fake_search))
        text = await search_funds.ainvoke({"keyword": "易方达蓝筹"})

        assert seen == {"keyword": "易方达蓝筹", "user_id": 42}
        payload = json.loads(text.split("\n")[1])
        assert payload["matches"][0]["fund_code"] == "005827"

    async def test_truncation_warning(self, monkeypatch):
        rows = [
            SimpleNamespace(fund_code=str(i).zfill(6), fund_name=f"基金{i}", fund_type="混合型") for i in range(15)
        ]

        async def fake_search(keyword, user_id):
            return rows

        _patch_tool_service(monkeypatch, "search_funds", SimpleNamespace(search=fake_search))
        text = await search_funds.ainvoke({"keyword": "基金", "limit": 5})
        assert "共 15 条匹配" in text
        assert text.count("fund_code") == 5 or '"fund_code"' in text

    async def test_service_failure_is_upstream_error(self, monkeypatch):
        async def boom(keyword, user_id):
            raise RuntimeError("db down with secret password=xxx")

        _patch_tool_service(monkeypatch, "search_funds", SimpleNamespace(search=boom))
        text = await search_funds.ainvoke({"keyword": "任意"})
        assert text.startswith("[TOOL_ERROR] UPSTREAM_ERROR")
        assert "password" not in text  # 内部异常细节不得外泄

    def test_schema_has_no_user_id(self):
        assert "user_id" not in search_funds.args


# ---------------------------------------------------------------------------
# get_fund_snapshot 的用例
# ---------------------------------------------------------------------------


class TestGetFundSnapshot:
    async def test_success_with_performance(self, monkeypatch):
        detail = SimpleNamespace(
            fund_code="005827",
            fund_name="易方达蓝筹精选",
            fund_type="混合型",
            company="易方达基金",
            manager_name="张坤",
            inception_date=date(2018, 9, 5),
            asset_size="600亿",
            latest_nav=1.5,
            accumulated_nav=1.9,
            nav_date=business_today() - timedelta(days=1),
            daily_return=0.5,
            performance=SimpleNamespace(model_dump=lambda exclude_none: {"return_1y": 12.5}),
            source="akshare",
            source_as_of=None,
        )

        async def fake_detail(code, user_id):
            seen_user_id.append(user_id)
            return detail

        seen_user_id: list[int] = []
        _patch_tool_service(monkeypatch, "get_fund_snapshot", SimpleNamespace(get_detail=fake_detail))
        text = await get_fund_snapshot.ainvoke({"fund_code": "005827"})

        assert seen_user_id == [42]
        assert "return_1y" in text
        assert "stale=true" not in text

    async def test_stale_nav_flagged(self, monkeypatch):
        detail = SimpleNamespace(
            fund_code="005827",
            fund_name="x",
            fund_type=None,
            company=None,
            manager_name=None,
            inception_date=None,
            asset_size=None,
            latest_nav=1.0,
            accumulated_nav=None,
            nav_date=business_today() - timedelta(days=10),
            daily_return=None,
            performance=None,
            source="akshare",
            source_as_of=None,
        )
        _patch_tool_service(
            monkeypatch,
            "get_fund_snapshot",
            SimpleNamespace(get_detail=lambda c, u: _async(detail)),
        )
        text = await get_fund_snapshot.ainvoke({"fund_code": "005827"})
        assert "stale=true" in text

    async def test_not_found(self, monkeypatch):
        async def fake_detail(code, user_id):
            return None

        _patch_tool_service(monkeypatch, "get_fund_snapshot", SimpleNamespace(get_detail=fake_detail))
        text = await get_fund_snapshot.ainvoke({"fund_code": "999999"})
        assert "[TOOL_ERROR] FUND_NOT_FOUND" in text

    async def test_invalid_code_not_silently_fixed(self, monkeypatch):
        text = await get_fund_snapshot.ainvoke({"fund_code": "11011"})
        assert "[TOOL_ERROR] INVALID_ARGUMENT" in text
        assert "11011" in text


# ---------------------------------------------------------------------------
# get_fund_history 的用例
# ---------------------------------------------------------------------------


class TestGetFundHistory:
    @staticmethod
    def _history_response(days=10):
        base = business_today() - timedelta(days=days)
        points = [SimpleNamespace(nav_date=base + timedelta(days=i), unit_nav=1.0 + i / 100) for i in range(days)]
        return SimpleNamespace(fund_code="005827", range="1y", total=days, has_more=False, points=points)

    async def test_weekly_sampling(self, monkeypatch):
        seen = {}

        async def fake_history(
            fund_code, start_date=None, end_date=None, range_key=None, limit=None, before_date=None
        ):
            seen.update(range_key=range_key)
            return self._history_response(days=30)

        _patch_tool_service(
            monkeypatch,
            "get_fund_history",
            SimpleNamespace(get_nav_history=fake_history),
        )
        text = await get_fund_history.ainvoke({"fund_code": "005827", "range_key": "1y"})

        assert seen["range_key"] == "1y"
        payload = json.loads(text.split("\n")[1])
        assert payload["granularity"] == "weekly"
        assert payload["points"][-1]["date"] == (business_today()).isoformat() or payload["points"]

    async def test_missing_range_and_dates_rejected(self, monkeypatch):
        text = await get_fund_history.ainvoke({"fund_code": "005827"})
        assert "[TOOL_ERROR] INVALID_ARGUMENT" in text


# ---------------------------------------------------------------------------
# get_fund_holdings 的用例
# ---------------------------------------------------------------------------


class TestGetFundHoldings:
    async def test_success_keeps_report_date(self, monkeypatch):
        response = SimpleNamespace(
            quarter="2026年2季度",
            previous_quarter="2026年1季度",
            items=[
                SimpleNamespace(
                    stock_code="600519", stock_name="贵州茅台", weight=9.5, weight_change=0.3, is_new=False
                )
            ],
            industries=[SimpleNamespace(industry="白酒", weight=30.0)],
            industries_as_of=date(2026, 6, 30),
        )

        async def fake_holdings(code):
            return response

        _patch_tool_service(monkeypatch, "get_fund_holdings", SimpleNamespace(get_holdings=fake_holdings))
        text = await get_fund_holdings.ainvoke({"fund_code": "005827"})

        assert "2026年2季度" in text
        assert "定期披露" in text
        assert "贵州茅台" in text

    async def test_empty_disclosure_is_data_not_available(self, monkeypatch):
        response = SimpleNamespace(quarter=None, previous_quarter=None, items=[], industries=[], industries_as_of=None)

        async def fake_holdings(code):
            return response

        _patch_tool_service(monkeypatch, "get_fund_holdings", SimpleNamespace(get_holdings=fake_holdings))
        text = await get_fund_holdings.ainvoke({"fund_code": "005827"})
        assert "[TOOL_ERROR] DATA_NOT_AVAILABLE" in text


# ---------------------------------------------------------------------------
# get_portfolio / get_positions 的用例
# ---------------------------------------------------------------------------


class TestPortfolioTools:
    async def test_get_portfolio_passes_runtime_user_id(self, monkeypatch):
        seen = {}

        async def fake_summary(user_id, account_id=None):
            seen.update(user_id=user_id, account_id=account_id)
            return SimpleNamespace(
                fund_count=2,
                total_market_value=10000.0,
                total_cost=9000.0,
                total_profit_loss=1000.0,
                total_profit_loss_rate=0.1111,
                daily_profit_loss=12.0,
                data_updated_at=utc_now(),
            )

        _patch_tool_service(monkeypatch, "get_portfolio", SimpleNamespace(get_summary=fake_summary))
        text = await get_portfolio.ainvoke({})

        assert seen == {"user_id": 42, "account_id": None}
        assert '"total_market_value":10000.0' in text

    async def test_get_positions_sorted_and_capped(self, monkeypatch):
        seen = {}

        async def fake_positions(user_id, account_id=None):
            seen.update(user_id=user_id, account_id=account_id)
            return [
                SimpleNamespace(
                    fund_code=f"{i:06d}",
                    fund_name=f"基金{i}",
                    account_id=1,
                    shares=10.0,
                    cost_amount=100.0,
                    market_value=float(1000 - i),
                    profit_loss=10.0,
                    profit_loss_rate=0.1,
                    position_ratio=0.5 - i / 10,
                    daily_profit_loss=1.0,
                    nav_date=date(2026, 9, 29),
                    updated_at=None,
                )
                for i in range(5)
            ]

        _patch_tool_service(monkeypatch, "get_positions", SimpleNamespace(list_positions=fake_positions))
        text = await get_positions.ainvoke({"limit": 3})

        assert seen == {"user_id": 42, "account_id": None}
        payload = json.loads(text.split("\n")[1])
        values = [row["market_value"] for row in payload["positions"]]
        assert values == sorted(values, reverse=True)
        assert len(payload["positions"]) == 3
        assert "仅返回市值最大的前 3 只" in text

    @pytest.mark.parametrize("tool", [get_portfolio, get_positions])
    def test_schema_has_no_user_id(self, tool):
        assert "user_id" not in tool.args


class TestWatchlistTools:
    async def test_get_watchlist_passes_runtime_user_id_and_caps(self, monkeypatch):
        seen = {}

        async def fake_watchlist(user_id, group_id=None):
            seen.update(user_id=user_id, group_id=group_id)
            return [
                SimpleNamespace(
                    fund_code="000001",
                    fund_name="华夏成长",
                    fund_type="混合型",
                    latest_nav=1.025,
                    nav_date=date(2026, 10, 22),
                    daily_return=-3.67,
                    weekly_return=-15.2,
                    monthly_return=-22.76,
                    quarterly_return=-25.13,
                    semiannual_return=-9.05,
                    annual_return=-3.48,
                    is_held=True,
                    is_updated=True,
                    groups=["稳健"],
                    group_ids=[7],
                ),
                SimpleNamespace(
                    fund_code="011452",
                    fund_name="华泰柏瑞质量成长",
                    fund_type="混合型",
                    latest_nav=2.2175,
                    nav_date=date(2026, 10, 21),
                    daily_return=1.75,
                    weekly_return=2.0,
                    monthly_return=-29.12,
                    quarterly_return=-20.1,
                    semiannual_return=-24.62,
                    annual_return=48.78,
                    is_held=False,
                    is_updated=False,
                    groups=[],
                    group_ids=[],
                ),
            ]

        _patch_tool_service(monkeypatch, "get_watchlist", SimpleNamespace(list_funds=fake_watchlist))
        text = await get_watchlist.ainvoke({"group_id": 7, "limit": 1})

        assert seen == {"user_id": 42, "group_id": 7}
        payload = json.loads(text.split("\n")[1])
        assert payload["watchlist_count"] == 1
        assert payload["return_unit"] == "percentage_point"
        assert payload["watchlist"][0]["fund_code"] == "000001"
        assert payload["watchlist"][0]["groups"] == ["稳健"]
        assert "仅返回前 1 只" in text

    async def test_get_watchlist_marks_stale_navs(self, monkeypatch):
        item = SimpleNamespace(
            fund_code="011452",
            fund_name="华泰柏瑞质量成长",
            fund_type=None,
            latest_nav=None,
            nav_date=None,
            daily_return=None,
            weekly_return=None,
            monthly_return=None,
            quarterly_return=None,
            semiannual_return=None,
            annual_return=None,
            is_held=False,
            is_updated=False,
            groups=[],
            group_ids=[],
        )

        async def fake_watchlist(user_id, group_id=None):
            return [item]

        _patch_tool_service(monkeypatch, "get_watchlist", SimpleNamespace(list_funds=fake_watchlist))
        text = await get_watchlist.ainvoke({})

        assert "stale=true" in text
        assert "部分自选基金的净值可能不是最新" in text
        payload = json.loads(text.split("\n")[1])
        assert payload["watchlist"][0]["nav_is_updated"] is False

    def test_schema_has_no_user_id(self):
        assert "user_id" not in get_watchlist.args


# ---------------------------------------------------------------------------
# get_market_context 的用例
# ---------------------------------------------------------------------------


class TestGetMarketContext:
    async def test_success(self, monkeypatch):
        quotes = [
            SimpleNamespace(
                index_code="sh000001", name="上证指数", close=3000.0, change_pct=0.5, trade_date=business_today()
            ),
        ]

        async def fake_quotes():
            return quotes

        _patch_tool_service(monkeypatch, "get_market_context", SimpleNamespace(get_quotes=fake_quotes))
        text = await get_market_context.ainvoke({})
        assert "上证指数" in text
        assert "3000.0" in text

    async def test_empty_is_data_not_available(self, monkeypatch):
        async def fake_quotes():
            return []

        _patch_tool_service(monkeypatch, "get_market_context", SimpleNamespace(get_quotes=fake_quotes))
        text = await get_market_context.ainvoke({})
        assert "[TOOL_ERROR] DATA_NOT_AVAILABLE" in text


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner()


def test_drop_nones_prunes_recursively():
    assert tool_common.drop_nones({"a": None, "b": {"c": None, "d": 1}, "e": [None, 2]}) == {
        "b": {"d": 1},
        "e": [2],
    }
