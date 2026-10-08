"""港股系指数的实时价：基准法要用的那条指数不在 A 股目录里时，从腾讯补一份.

只认白名单里那几条指数，名字对不上就不给价。把"恒生医疗保健"当成"恒生指数"拿去
加权，得到的是一个看起来完全合理、错到不知在哪里的数——那比空着更糟。

中证/国证的港股通系列指数（如 931250 港股通创新药）这里取不到：腾讯不认 9 字头
代码，东财 push2 在这台机器上时好时坏（同一批请求首轮 200、复测 RemoteProtocolError），
不能当依赖。所以跟踪这类指数的基金仍然会走到"无估值依据"，除非它的披露持仓够穿透。
"""

from collections.abc import Iterable
from datetime import date

from app.core.logging import logger
from app.integrations.fund_data.tencent_client import fetch_quotes
from app.schemas.market import IndexQuoteItem

# 基准里常见的写法 → 腾讯代码。**必须精确匹配**：解析器把「恒生科技指数收益率」吃成
# 「恒生科技」这种去尾形式，而「恒生医疗保健」和「恒生指数」是两条完全不同的指数，
# 用"包含"匹配会把它当成恒生指数去加权——那是个看起来完全合理、错到不知在哪里的数。
# 认不出就不给价，让这只基金走降级链。
_HK_INDEX_SYMBOLS = {
    "恒生": "hkHSI",
    "恒生指数": "hkHSI",
    "香港恒生指数": "hkHSI",
    "恒生科技": "hkHSTECH",
    "恒生科技指数": "hkHSTECH",
    "恒生中国企业": "hkHSCEI",
    "恒生中国企业指数": "hkHSCEI",
    "国企": "hkHSCEI",
    "国企指数": "hkHSCEI",
    "红筹": "hkHSCCI",
    "红筹指数": "hkHSCCI",
}


def hk_symbol(index_name: str) -> str | None:
    """这条基准指数名能不能映射到一个有实时价的港股系指数."""
    return _HK_INDEX_SYMBOLS.get(index_name.strip())


async def fetch_hk_index_quotes(index_names: Iterable[str]) -> dict[str, IndexQuoteItem]:
    """按基准里出现的指数名取港股系实时价，结果以**基准用的名字**为键.

    键必须是基准里那个名字，否则 `_benchmark_ready` 按 `part.index_name` 查不到，
    基准法会因为"取到价了但对不上号"而放弃。
    """
    wanted = {name: hk_symbol(name) for name in set(index_names)}
    symbols = sorted({symbol for name, symbol in wanted.items() if symbol})
    if not symbols:
        return {}

    quotes = {}
    try:
        rows = await fetch_quotes(symbols)
    except Exception as error:  # 行情源挂了不影响其它基金，这只基金照常走降级链。
        logger.warning("hk_index_quotes_failed", symbols=symbols, error=str(error)[:120])
        return {}

    by_symbol = {row.symbol: row for row in rows}
    for name, symbol in wanted.items():
        row = by_symbol.get(symbol or "")
        if row is None or row.change_pct is None:
            continue
        quotes[name] = IndexQuoteItem(
            index_code=symbol or "",
            name=name,
            close=row.price,
            change_pct=row.change_pct,
            trade_date=_quote_date(row.quote_time),
        )
    return quotes


def _quote_date(quote_time: str | None) -> date | None:
    """报价时间戳里的日期，取不到就当没有（界面会显示行情日期缺失）.

    腾讯给港股指数的那串时间是 `2026/10/08 16:08:40`（斜杠），A 股才是横杠，
    而 `MarketExternalQuote.quote_time` 的注释写的是"已归一化"——两种都得认，
    否则日期会静默变成 None，界面上就看不出这条行情是哪天的。
    """
    if not quote_time or len(quote_time) < 10:
        return None
    try:
        return date.fromisoformat(quote_time[:10].replace("/", "-"))
    except ValueError:
        return None
