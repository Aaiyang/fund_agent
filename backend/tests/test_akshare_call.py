"""Every AKShare endpoint is called with keyword arguments, so they must survive the hop into the worker thread."""

import asyncio
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
