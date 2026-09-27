"""Tencent quote feed behind the market analysis screen.

Chosen over AKShare for this one screen because it is the only source reachable
from this network that covers A股, 港股, 美股 and 指数 together, including daily
bars and the current session's minute line. Eastmoney's push2 hosts answer
intermittently at best, and AKShare's own stock helpers fail outright because
``requests`` picks up a system proxy that ``httpx`` here ignores.

The company profile is the one exception: it comes from Eastmoney's F10 data
center, which is stable, and only exists for A股 listings.
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
# One request caps at this many bars; the longest range on the screen still fits.
_MAX_BARS = 1200
# Only Shanghai and Shenzhen have an F10 record in the data center.
_A_SHARE_PREFIXES = {"sh": "SH", "sz": "SZ"}


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_quotes(symbols: list[str]) -> list[MarketExternalQuote]:
    """Fetch snapshots for canonical symbols in one batched request.

    An unparsable body yields fewer quotes rather than an error, which the
    screen renders as missing numbers.
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
    """Return the symbol the bar endpoint actually serves data for.

    US listings need their exchange suffix: ``usAAPL`` quotes fine but its K-line
    reply is a two-row stub, while ``usAAPL.OQ`` returns the full history. The
    quote feed reports the suffixed code, so one cheap lookup fixes the shape.
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
    """Fetch adjusted bars for one instrument.

    ``symbol`` must already be canonical (see ``tencent_symbol``); US listings
    additionally need their exchange suffix, which the caller resolves with
    :func:`resolve_symbol` because the bare ticker returns a stub.
    """
    # The param string is symbol,period,start_date,end_date,count,adjust; leaving
    # both dates empty is how the feed is asked for the most recent N bars.
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
    """Fetch the current session's minute line, per-minute volumes included."""
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
    """Fetch the last five sessions' minute lines, stitched oldest-first.

    美股 has no data here (the reply is an empty list), same as for the single
    session. The window's reference close is not part of the reply either.
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
    """Fetch A股 master data; other markets return None without a request."""
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
