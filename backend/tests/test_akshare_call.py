"""所有 AKShare 接口都靠关键字参数被调用，因此这些参数必须原样传到 worker 线程那一侧."""

import asyncio
import time
import types

from app.integrations.fund_data import akshare_provider as module
from app.integrations.fund_data.akshare_provider import AKShareFundProvider


class _Frame:
    """给 AKShare 返回的 DataFrame 做一个最小可用的替身."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, _orient: str) -> list[dict[str, object]]:
        return self._rows


def test_call_forwards_keyword_arguments_to_the_akshare_function(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_fetch(symbol: str, indicator: str) -> _Frame:
        seen["symbol"] = symbol
        seen["indicator"] = indicator
        return _Frame([{"净值日期": "2026-09-22"}])

    monkeypatch.setattr(module, "AKSHARE_AVAILABLE", True)
    monkeypatch.setattr(module, "ak", types.SimpleNamespace(fund_open_fund_info_em=fake_fetch))

    rows = asyncio.run(
        AKShareFundProvider()._call("fund_open_fund_info_em", symbol="011452", indicator="单位净值走势")  # noqa: SLF001
    )

    assert rows == [{"净值日期": "2026-09-22"}]
    assert seen == {"symbol": "011452", "indicator": "单位净值走势"}


def test_call_raises_when_the_akshare_function_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(module, "AKSHARE_AVAILABLE", True)
    monkeypatch.setattr(module, "ak", types.SimpleNamespace())

    try:
        asyncio.run(AKShareFundProvider()._call("no_such_endpoint", symbol="011452"))  # noqa: SLF001
    except ValueError as error:
        assert "no_such_endpoint" in str(error)
    else:
        raise AssertionError("a missing endpoint must surface, not return an empty list")


def _rank_rows(code: str, nav: float) -> list[dict[str, object]]:
    return [
        {
            "基金代码": code,
            "基金简称": "测试基金",
            "单位净值": nav,
            "累计净值": nav + 0.2,
            "日期": "2026-09-30",
            "日增长率": 0.28,
        }
    ]


def _rank_provider(monkeypatch, fetch) -> tuple[AKShareFundProvider, list[str]]:
    calls: list[str] = []

    def fake_rank(symbol: str) -> _Frame:
        calls.append(symbol)
        return _Frame(fetch(len(calls)))

    monkeypatch.setattr(module, "AKSHARE_AVAILABLE", True)
    monkeypatch.setattr(module, "ak", types.SimpleNamespace(fund_open_fund_rank_em=fake_rank))
    return AKShareFundProvider(), calls


def _age(provider: AKShareFundProvider, seconds: float) -> None:
    """把缓存的时钟往回拨，测试里才能跑到有效期已过期这条分支."""
    provider._rank_cached_at -= seconds  # noqa: SLF001
    provider._rank_attempted_at -= seconds  # noqa: SLF001


def test_a_forced_read_refetches_the_rank_table_and_carries_accumulated_nav(monkeypatch) -> None:
    """按需刷新要拿到新表，而普通读取得继续保持廉价.

    那张批量表一次请求就能答复所有基金，所以普通读取沿用很长的缓存期；`force`
    —— 打开持仓页走的就是它 —— 则绕过缓存。紧接在一次强制刷新之后再强制刷新会被
    拒绝：两次重建挨得这么近，不可能都值回那点带宽。
    """
    provider, calls = _rank_provider(monkeypatch, lambda attempt: _rank_rows("005918", 1.5))

    first = asyncio.run(provider.get_latest_navs(["005918"]))
    cached = asyncio.run(provider.get_latest_navs(["005918"]))
    _age(provider, 7 * 3600)
    forced = asyncio.run(provider.get_latest_navs(["005918"], force=True))
    refused = asyncio.run(provider.get_latest_navs(["005918"], force=True))

    assert calls == ["全部", "全部"]
    assert all(len(rows) == 1 for rows in (first, cached, forced, refused))
    assert {rows[0].unit_nav for rows in (first, cached, forced, refused)} == {1.5}
    assert forced[0].accumulated_nav == 1.7
    assert forced[0].daily_return == 0.28


def test_concurrent_forced_reads_share_one_rank_table_fetch(monkeypatch) -> None:
    """两个用户同时打开这个页面，也只付出一次覆盖全部基金的请求."""

    def slow(_attempt: int) -> list[dict[str, object]]:
        time.sleep(0.05)
        return _rank_rows("005918", 1.5)

    provider, calls = _rank_provider(monkeypatch, slow)

    async def both() -> None:
        await asyncio.gather(*(provider.get_latest_navs(["005918"], force=True) for _ in range(2)))

    asyncio.run(both())
    assert len(calls) == 1


def test_a_failed_rebuild_leaves_the_previous_table_serving(monkeypatch) -> None:
    """上游不可用时，每个时间窗只试一次，而不是每切一次标签页就试一次."""

    def failing(attempt: int) -> list[dict[str, object]]:
        if attempt == 1:
            return _rank_rows("005918", 1.5)
        raise RuntimeError("source unavailable")

    provider, calls = _rank_provider(monkeypatch, failing)

    asyncio.run(provider.get_latest_navs(["005918"]))
    _age(provider, 120)
    for _ in range(2):
        try:
            asyncio.run(provider.get_latest_navs(["005918"], force=True))
        except RuntimeError:
            pass

    assert len(calls) == 2
    assert [row.unit_nav for row in asyncio.run(provider.get_latest_navs(["005918"]))] == [1.5]
