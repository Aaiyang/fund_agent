"""Every AKShare endpoint is called with keyword arguments, so they must survive the hop into the worker thread."""

import asyncio
import time
import types

from app.integrations.fund_data import akshare_provider as module
from app.integrations.fund_data.akshare_provider import AKShareFundProvider


class _Frame:
    """Minimal stand-in for the DataFrame AKShare returns."""

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
    """Wind the cache clocks back so a time-to-live can be exercised in a test."""
    provider._rank_cached_at -= seconds  # noqa: SLF001
    provider._rank_attempted_at -= seconds  # noqa: SLF001


def test_a_forced_read_refetches_the_rank_table_and_carries_accumulated_nav(monkeypatch) -> None:
    """The on-demand refresh needs a new table; a stale read must stay cheap.

    The batched table answers every fund in one request, so a plain read keeps
    the long cache, while `force` — what opening 持仓 does — ignores it. A forced
    read immediately after another is refused: two rebuilds a part cannot both
    be worth their bandwidth.
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
    """Two users opening the screen at once cost one request over every fund."""

    def slow(_attempt: int) -> list[dict[str, object]]:
        time.sleep(0.05)
        return _rank_rows("005918", 1.5)

    provider, calls = _rank_provider(monkeypatch, slow)

    async def both() -> None:
        await asyncio.gather(*(provider.get_latest_navs(["005918"], force=True) for _ in range(2)))

    asyncio.run(both())
    assert len(calls) == 1


def test_a_failed_rebuild_leaves_the_previous_table_serving(monkeypatch) -> None:
    """An outage costs one attempt per window, not one per tab focus."""

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
