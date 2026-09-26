"""Sina quote feed for individual-stock prices.

Eastmoney's push2 quote hosts are unreachable from this network and its fund
estimate API has been retired, so stock quotes come from Sina's batched
``hq.sinajs.cn`` endpoint: one request covers A-share, Hong Kong and US
listings together, which is what a QDII fund's top ten actually needs.
"""

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import logger
from app.integrations.fund_data.models import StockExternalQuote
from app.integrations.fund_data.normalizer import parse_sina_quotes

_QUOTE_TIMEOUT_SECONDS = 8.0
# The feed rejects requests without a same-family Referer.
_QUOTE_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_quotes(symbols: list[str]) -> list[StockExternalQuote]:
    """Fetch quotes for prefixed symbols (sz300570, hk01810, gb_aapl, ...).

    A transport failure raises; an unparsable body yields fewer quotes, which
    the caller renders as missing prices rather than an error page.
    """
    if not symbols:
        return []

    async with httpx.AsyncClient(timeout=_QUOTE_TIMEOUT_SECONDS) as client:
        response = await client.get("https://hq.sinajs.cn/list=" + ",".join(symbols), headers=_QUOTE_HEADERS)
        response.raise_for_status()

    quotes = parse_sina_quotes(response.text)
    logger.debug("stock_quotes_fetched", requested=len(symbols), returned=len(quotes))
    return quotes
