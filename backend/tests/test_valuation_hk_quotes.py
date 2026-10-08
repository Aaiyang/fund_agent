"""港股系指数取价的映射与降级：只认白名单，认不出就不给价."""

from datetime import date

from app.integrations.fund_data.models import MarketExternalQuote
from app.integrations.valuation import hk_quotes
from app.integrations.valuation.hk_quotes import _quote_date, fetch_hk_index_quotes, hk_symbol


def test_the_known_hang_seng_family_maps_to_tencent_symbols() -> None:
    # 基准解析出来的是去尾形式（「恒生科技指数收益率」→「恒生科技」），两种写法都收。
    assert hk_symbol("恒生科技") == "hkHSTECH"
    assert hk_symbol("恒生科技指数") == "hkHSTECH"
    assert hk_symbol("恒生") == "hkHSI"
    assert hk_symbol("恒生指数") == "hkHSI"
    assert hk_symbol("恒生中国企业") == "hkHSCEI"
    assert hk_symbol("红筹指数") == "hkHSCCI"


def test_an_unknown_hang_seng_index_is_not_guessed() -> None:
    """恒生医疗保健不是恒生指数。宁可取不到价走降级，也不能拿大盘指数替它加权."""
    assert hk_symbol("恒生医疗保健") is None
    assert hk_symbol("恒生综合") is None
    # 中证/国证的港股通系列指数（931250 这类）腾讯没有，这里必须承认取不到。
    assert hk_symbol("中证港股通创新药") is None


def test_quote_date_tolerates_a_missing_or_malformed_timestamp() -> None:
    assert _quote_date("2026-10-08 16:08:40") == date(2026, 10, 8)
    # 腾讯给港股指数的时间是斜杠格式，模型注释里那句"已归一化"对它不成立。
    assert _quote_date("2026/10/08 16:08:40") == date(2026, 10, 8)
    assert _quote_date(None) is None
    assert _quote_date("16:08:40") is None
    assert _quote_date("不是时间") is None


async def test_quotes_are_keyed_by_the_benchmark_name(monkeypatch) -> None:
    """键必须是基准里那个名字，否则 `_benchmark_ready` 按 part.index_name 查不到."""

    async def _fake(symbols: list[str]) -> list[MarketExternalQuote]:
        return [
            MarketExternalQuote(
                symbol=sym,
                kind="index",
                name="恒生科技指数",
                price=4073.38,
                change_pct=-2.89,
                quote_time="2026-10-08 16:08:40",
            )
            for sym in symbols
        ]

    monkeypatch.setattr(hk_quotes, "fetch_quotes", _fake)
    quotes = await fetch_hk_index_quotes(["恒生科技", "中证800", "恒生"])

    assert set(quotes) == {"恒生科技", "恒生"}
    assert quotes["恒生科技"].change_pct == -2.89
    assert quotes["恒生科技"].trade_date == date(2026, 10, 8)


async def test_a_dead_quote_source_degrades_to_no_quotes(monkeypatch) -> None:
    """行情源挂了不能把整批估值带走，也不能抛到接口上."""

    async def _boom(symbols: list[str]) -> list[MarketExternalQuote]:
        raise RuntimeError("RemoteProtocolError")

    monkeypatch.setattr(hk_quotes, "fetch_quotes", _boom)

    assert await fetch_hk_index_quotes(["恒生科技"]) == {}
