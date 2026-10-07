"""行情分析页背后的腾讯数据源.

这一页不用 AKShare：在本网络里，它是唯一能同时覆盖 A股、港股、美股和指数，
还给出日线与当日分时线的源。东财 push2 的行情主机最多时好时坏，AKShare 自带的
股票接口则直接失败——``requests`` 会读系统代理，而这里的 ``httpx`` 不读。

公司主数据是唯一的例外：它取自东财的 F10 数据中心，那边稳定，但只有 A股 标的
才有.
"""

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import logger
from app.integrations.fund_data.models import (
    CandleExternalBar,
    CompanyExternalProfile,
    MarketExternalQuote,
    MinuteExternalSeries,
)
from app.integrations.fund_data.normalizer import (
    normalize_company_rows,
    parse_tencent_candles,
    parse_tencent_day_query,
    parse_tencent_minutes,
    parse_tencent_quotes,
)

_TIMEOUT_SECONDS = 8.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_QUOTES_URL = "https://qt.gtimg.cn/q="
_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
_DAY_QUERY_URL = "https://web.ifzq.gtimg.cn/appstock/app/day/query"
_PROFILE_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
# 单次请求最多取这么多根 K 线，页面上最长的区间也照样装得下。
_MAX_BARS = 1200
# 数据中心里只有沪市和深市有 F10 记录。
_A_SHARE_PREFIXES = {"sh": "SH", "sz": "SZ"}


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_quotes(symbols: list[str]) -> list[MarketExternalQuote]:
    """一次批量请求取这些规范代码的快照.

    响应体解析不出来时返回更少条而不报错，页面把它显示成缺数.
    """
    if not symbols:
        return []

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(_QUOTES_URL + ",".join(symbols), headers=_HEADERS)
        response.raise_for_status()

    quotes = parse_tencent_quotes(response.text)
    logger.debug("market_quotes_fetched", requested=len(symbols), returned=len(quotes))
    return quotes


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def resolve_symbol(symbol: str) -> str:
    """返回 K 线接口真正有数据的那个代码.

    美股标的必须带交易所后缀：``usAAPL`` 取行情没问题，但 K 线只回两行占位数
    据，``usAAPL.OQ`` 才有完整历史。行情接口会把带后缀的代码报出来，所以花一次
    很便宜的查询就能把形状补对.
    """
    if not symbol.startswith("us") or "." in symbol:
        return symbol

    quotes = await fetch_quotes([symbol])
    listing = quotes[0].listing_code if quotes else None
    return f"us{listing}" if listing else symbol


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_candles(symbol: str, period: str = "day", count: int = 250) -> list[CandleExternalBar]:
    """取单个标的的复权 K 线.

    ``symbol`` 必须已经是规范形式（见 ``tencent_symbol``）；美股还要额外带交易所
    后缀，裸 ticker 只会拿到占位数据，所以调用方先用 :func:`resolve_symbol` 解析.
    """
    # param 串依次是 symbol,period,start_date,end_date,count,adjust；两个日期
    # 都留空，就是向接口要最近 N 根 K 线。
    params = {"param": f"{symbol},{period},,,{max(1, min(count, _MAX_BARS))},qfq"}
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(_KLINE_URL, params=params, headers=_HEADERS)
        response.raise_for_status()
        payload = response.json()

    bars = parse_tencent_candles(payload, symbol)
    logger.debug("market_candles_fetched", symbol=symbol, period=period, returned=len(bars))
    return bars


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_minutes(symbol: str) -> MinuteExternalSeries:
    """取当日分时线，连每分钟的成交量一起."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(_MINUTE_URL, params={"code": symbol}, headers=_HEADERS)
        response.raise_for_status()
        payload = response.json()

    series = parse_tencent_minutes(payload, symbol)
    logger.debug("market_minutes_fetched", symbol=symbol, returned=len(series.points))
    return series


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_recent_minutes(symbol: str) -> MinuteExternalSeries:
    """取最近五个交易日的分时线，按从早到晚拼起来.

    这里美股没有数据（返回空列表），跟单日分时一样；整段的基准昨收也不在返回
    里.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(_DAY_QUERY_URL, params={"code": symbol}, headers=_HEADERS)
        response.raise_for_status()
        payload = response.json()

    series = parse_tencent_day_query(payload, symbol)
    logger.debug("market_five_day_fetched", symbol=symbol, returned=len(series.points))
    return series


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_company_profile(symbol: str) -> CompanyExternalProfile | None:
    """取 A股 主数据；其他市场不发请求，直接返回 None."""
    suffix = _A_SHARE_PREFIXES.get(symbol[:2])
    if suffix is None or not symbol[2:].isdigit():
        return None

    params = {
        "reportName": "RPT_F10_ORG_BASICINFO",
        "columns": "ALL",
        "filter": f'(SECUCODE="{symbol[2:]}.{suffix}")',
        "pageNumber": "1",
        "pageSize": "1",
        "source": "HSF10",
        "client": "PC",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(
            _PROFILE_URL, params=params, headers={**_HEADERS, "Referer": "https://emweb.securities.eastmoney.com/"}
        )
        response.raise_for_status()
        payload = response.json()

    return normalize_company_rows(payload, symbol)
