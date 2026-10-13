"""有界异步的板块数据适配：东财目录与报价、新浪涨跌榜，不把模型输入直接拼成上游地址."""

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.integrations.fund_data.models import MarketExternalQuote
from app.integrations.fund_data.normalizer import to_float
from app.schemas.sector import SectorBoardItem, SectorBoardKind, SectorBoardStock, SectorItem, SectorKind
from app.utils.market_quote_policy import finite_number

_ENDPOINTS = {
    "clist/get": (
        "https://79.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    ),
    "stock/get": (
        "https://91.push2.eastmoney.com/api/qt/stock/get",
        "https://push2.eastmoney.com/api/qt/stock/get",
    ),
}
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
_SEMAPHORE = asyncio.Semaphore(4)
_PAGE_SIZE = 100
_MAX_PAGES = 20


class SectorDataUnavailable(ValueError):
    """目录不完整或上游没有可核验报价."""


async def _request_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """同源固定主机列表；仅网络故障由 tenacity 退避后切备用主机."""
    endpoints = _ENDPOINTS[path]
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.HTTPError, OSError)),
        stop=stop_after_attempt(len(endpoints)),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        reraise=True,
    ):
        with attempt:
            async with _SEMAPHORE:
                async with httpx.AsyncClient(timeout=8) as client:
                    endpoint = endpoints[attempt.retry_state.attempt_number - 1]
                    response = await client.get(endpoint, params=params, headers=_HEADERS)
                    response.raise_for_status()
                    payload = response.json()
            if not isinstance(payload, dict) or payload.get("rc", 0) != 0:
                raise SectorDataUnavailable("板块数据源返回无效结果")
            return payload
    raise SectorDataUnavailable("板块数据源不可用")


async def fetch_sector_catalog(kind: SectorKind) -> list[SectorItem]:
    """稳定按代码分页，全部获取才返回；拒绝重复页和异常总量."""
    if kind not in {"industry", "concept"}:
        raise ValueError("不支持的板块类别")
    items: dict[str, SectorItem] = {}
    expected = None
    for page in range(1, _MAX_PAGES + 1):
        payload = await _request_json(
            "clist/get",
            {
                "pn": page,
                "pz": _PAGE_SIZE,
                "po": 0,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": "m:90 t:2 f:!50" if kind == "industry" else "m:90 t:3 f:!50",
                "fields": "f12,f14",
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SectorDataUnavailable("板块目录不可用")
        total = data.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or not 0 < total <= _MAX_PAGES * _PAGE_SIZE:
            raise SectorDataUnavailable("板块目录总量异常")
        if expected is not None and total != expected:
            raise SectorDataUnavailable("板块目录分页期间发生变化，请重试")
        expected = total
        rows = data.get("diff")
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, list) or not rows:
            raise SectorDataUnavailable("板块目录分页不完整")
        before = len(items)
        for row in rows:
            if not isinstance(row, dict):
                continue
            code, name = row.get("f12"), row.get("f14")
            if isinstance(code, str) and re.fullmatch(r"BK\d{4,6}", code) and isinstance(name, str) and name.strip():
                items[code] = SectorItem(sector_code=code, name=name.strip(), sector_type=kind)
        if len(items) == before:
            raise SectorDataUnavailable("板块目录返回重复页或无效数据")
        if len(items) > total:
            raise SectorDataUnavailable("板块目录数量超过声明总量")
        if len(items) == total:
            return list(items.values())
    raise SectorDataUnavailable("板块目录超过分页上限")


async def fetch_sector_quote(item: SectorItem) -> MarketExternalQuote:
    """固定整数报价协议：点位按 f59 小数位缩放，涨跌幅按100缩放，f86为来源Unix时间."""
    # 即使模型绕过 Pydantic 构造，也不能传递任意 secid / URL。
    if not re.fullmatch(r"BK\d{4,6}", item.sector_code):
        raise ValueError("无效板块代码")
    payload = await _request_json(
        "stock/get",
        {
            "secid": "90." + item.sector_code,
            "fltt": 1,
            "invt": 2,
            "fields": "f43,f57,f58,f59,f86,f169,f170",
        },
    )
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("f57") != item.sector_code:
        raise SectorDataUnavailable("板块报价代码不匹配或无数据")
    precision = data.get("f59")
    if not isinstance(precision, int) or isinstance(precision, bool) or not 0 <= precision <= 6:
        raise SectorDataUnavailable("板块报价精度不可核验")
    divisor = 10**precision
    price = finite_number(to_float(data.get("f43")))
    change = finite_number(to_float(data.get("f169")))
    pct = finite_number(to_float(data.get("f170")))
    stamp = finite_number(to_float(data.get("f86")))
    quote_time = None
    if stamp is not None and stamp > 0:
        try:
            quote_time = datetime.fromtimestamp(stamp, UTC).astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return MarketExternalQuote(
        symbol=item.sector_code,
        kind="index",
        name=item.name,
        price=price / divisor if price is not None else None,
        change=change / divisor if change is not None else None,
        change_pct=pct / 100 if pct is not None else None,
        quote_time=quote_time,
    )


_SINA_BOARD_URLS: dict[str, str] = {
    "industry": "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
    "concept": "https://money.finance.sina.com.cn/q/view/newFLJK.php",
}
_SINA_BOARD_PARAMS: dict[str, dict[str, str]] = {"industry": {}, "concept": {"param": "class"}}
_SINA_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
SINA_BOARD_SOURCE = "sina_sector_board"

# 新浪每行是逗号分隔的定长串，且不给字段名，位置本身就是含义：
# 0 板块代码、1 板块名、2 成分股家数、3 板块均价、4 涨跌额、5 涨跌幅（百分点）、
# 6 成交量、7 成交额、8 领涨股代码、9 领涨股涨跌幅、10 领涨股价、11 领涨股涨跌额、12 领涨股名。
_BOARD_COLUMNS = 13
_COL_CODE = 0
_COL_NAME = 1
_COL_STOCK_COUNT = 2
_COL_PRICE = 3
_COL_CHANGE = 4
_COL_CHANGE_PCT = 5
_COL_VOLUME = 6
_COL_AMOUNT = 7
_COL_LEAD_CODE = 8
_COL_LEAD_PCT = 9
_COL_LEAD_NAME = 12


def _number(text: str) -> float | None:
    """上游的空串、'-' 和异常值都算未知，不折算成 0."""
    stripped = text.strip()
    if not stripped or stripped in {"-", "--"}:
        return None
    try:
        return finite_number(float(stripped))
    except ValueError:
        return None


def _count(text: str) -> int | None:
    value = _number(text)
    return int(value) if value is not None and value.is_integer() else None


def parse_sina_board(text: str, kind: SectorBoardKind) -> list[SectorBoardItem]:
    """把 `var X = {...};` 的板块串解成列表；单行不合格就丢掉这一行，不猜.

    上游整体是 GBK 文本，解码由调用方完成（这里只接已解码字符串，方便单测）。
    """
    payload_text = text.split("=", 1)[1].strip().rstrip(";") if "=" in text else ""
    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        raise SectorDataUnavailable("板块涨跌榜响应不是可读 JSON") from None
    if not isinstance(payload, dict):
        raise SectorDataUnavailable("板块涨跌榜结构异常")

    items: list[SectorBoardItem] = []
    for row in payload.values():
        if not isinstance(row, str):
            continue
        fields = row.split(",")
        if len(fields) != _BOARD_COLUMNS:
            continue
        code, name = fields[_COL_CODE].strip(), fields[_COL_NAME].strip()
        if not code or not name:
            continue
        lead_code = fields[_COL_LEAD_CODE].strip()
        lead_name = fields[_COL_LEAD_NAME].strip()
        items.append(
            SectorBoardItem(
                code=code,
                name=name,
                sector_type=kind,
                stock_count=_count(fields[_COL_STOCK_COUNT]),
                price=_number(fields[_COL_PRICE]),
                change=_number(fields[_COL_CHANGE]),
                change_pct=_number(fields[_COL_CHANGE_PCT]),
                volume=_number(fields[_COL_VOLUME]),
                amount=_number(fields[_COL_AMOUNT]),
                leading_stock=(
                    SectorBoardStock(code=lead_code, name=lead_name or None, change_pct=_number(fields[_COL_LEAD_PCT]))
                    if lead_code
                    else None
                ),
            )
        )
    return items


async def fetch_sina_sector_board(kind: SectorBoardKind) -> list[SectorBoardItem]:
    """一次请求拿全量板块榜；只有网络故障退避重试，解析问题不重试."""
    url = _SINA_BOARD_URLS.get(kind)
    if url is None:
        raise ValueError("不支持的板块类别")
    text = ""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.HTTPError, OSError)),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        reraise=True,
    ):
        with attempt:
            async with _SEMAPHORE:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.get(url, params=_SINA_BOARD_PARAMS[kind], headers=_SINA_HEADERS)
                    response.raise_for_status()
                    # 上游声明的字符集不可信，实测正文是 GBK。
                    text = response.content.decode("gbk", "replace")

    items = parse_sina_board(text, kind)
    if not items:
        raise SectorDataUnavailable("板块涨跌榜没有可用行")
    return items
