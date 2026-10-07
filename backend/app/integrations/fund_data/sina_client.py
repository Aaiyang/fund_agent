"""个股行情的新浪数据源.

本网络连不上东财 push2 的行情主机，它的基金估值接口也已经下线，所以股票行情
改走新浪的批量接口 ``hq.sinajs.cn``：一次请求就能同时拿到 A股、港股、美股，
而 QDII 基金的前十重仓正需要跨这三个市场.
"""

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import logger
from app.integrations.fund_data.models import StockExternalQuote
from app.integrations.fund_data.normalizer import parse_sina_quotes

_QUOTE_TIMEOUT_SECONDS = 8.0
# 不带同源 Referer 的请求会被接口直接拒掉。
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
    """按带前缀的代码（sz300570、hk01810、gb_aapl……）取行情.

    传输失败会抛异常；响应体解析不出来时只返回能解析的那几条，调用方按缺价
    处理，而不是弹错误页.
    """
    if not symbols:
        return []

    async with httpx.AsyncClient(timeout=_QUOTE_TIMEOUT_SECONDS) as client:
        response = await client.get("https://hq.sinajs.cn/list=" + ",".join(symbols), headers=_QUOTE_HEADERS)
        response.raise_for_status()

    quotes = parse_sina_quotes(response.text)
    logger.debug("stock_quotes_fetched", requested=len(symbols), returned=len(quotes))
    return quotes
