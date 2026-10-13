"""财联社公开事件窗口；固定请求参数，不外传用户持仓或查询词."""

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal, cast
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.analytics.event_links import classify_event, event_fingerprint
from app.core.logging import logger
from app.schemas.market_event import MarketEvent, MarketEventFeed
from app.utils.clock import utc_now

_SEMAPHORE = asyncio.Semaphore(2)
_MAX_PAGES = 5
_PAGE_SIZE = 20


class EventDataUnavailable(ValueError):
    """来源错误或无可验证事件，不能解释为没有重大事件."""


def parse_event(row: Any) -> MarketEvent | None:
    """读取来源id与Unix发布时间，仅保留有限报道片段."""
    if not isinstance(row, dict):
        return None
    source_id, stamp = row.get("id"), row.get("ctime")
    if not isinstance(source_id, int) or isinstance(source_id, bool) or not 0 < source_id < 10**16:
        return None
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
        return None
    try:
        published = datetime.fromtimestamp(stamp, UTC).astimezone(ZoneInfo("Asia/Shanghai"))
    except (ValueError, OverflowError, OSError):
        return None
    content = row.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.select("script,style"):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    raw_title = row.get("title")
    title = (
        BeautifulSoup(raw_title, "html.parser").get_text(" ", strip=True)
        if isinstance(raw_title, str) and raw_title.strip()
        else text.split("】", 1)[0].lstrip("【")[:120]
    )
    excerpt = text[:240]
    if not title or not excerpt:
        return None
    # 所有标签均由实际返回的片段生成，不能以未返回正文作为隐藏证据。
    categories, topics, factors = classify_event(title + " " + excerpt)
    priority = row.get("level")
    return MarketEvent(
        event_id=event_fingerprint(str(source_id), title[:180], excerpt, published.isoformat()),
        source_id=str(source_id),
        title=title[:180],
        excerpt=excerpt,
        published_at=published,
        source_url=f"https://www.cls.cn/detail/{source_id}",
        source_priority=cast(Literal["A", "B", "C"], priority)
        if isinstance(priority, str) and priority in {"A", "B", "C"}
        else "unknown",
        categories=categories,
        topics=topics,
        factors=factors,
    )


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=3),
    reraise=True,
)
async def _page(cursor: int) -> list[Any]:
    """公共网页签名算法不是密钥；网络故障有限退避，结构错误不重试."""
    params: dict[str, Any] = {
        "app": "CailianpressWeb",
        "category": "",
        "last_time": cursor,
        "os": "web",
        "refresh_type": "1",
        "rn": str(_PAGE_SIZE),
        "sv": "8.4.6",
    }
    params["sign"] = hashlib.md5(hashlib.sha1(urlencode(params).encode()).hexdigest().encode()).hexdigest()
    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                "https://www.cls.cn/v1/roll/get_roll_list",
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cls.cn/telegraph"},
            )
            response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise EventDataUnavailable("事件响应超过上限")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("errno") != 0 or not isinstance(payload.get("data"), dict):
        raise EventDataUnavailable("事件来源返回错误")
    rows = payload["data"].get("roll_data")
    if not isinstance(rows, list) or len(rows) > _PAGE_SIZE:
        raise EventDataUnavailable("事件分页不可核验")
    return rows


async def fetch_event_feed() -> MarketEventFeed:
    """最多五页百条，重复页/中途失败保留部分状态，不假称覆盖全部请求时段."""
    stamp = utc_now()
    cursor = int(stamp.replace(tzinfo=UTC).timestamp())
    events: dict[str, MarketEvent] = {}
    scanned, invalid, partial, cap = 0, 0, False, False
    for page in range(_MAX_PAGES):
        try:
            rows = await _page(cursor)
        except Exception:
            if not events:
                raise
            logger.exception("event_feed_page_failed", page=page + 1)
            partial = True
            break
        if not rows:
            break
        before = len(events)
        scanned += len(rows)
        for raw in rows:
            event = parse_event(raw)
            if event is None or event.published_at.timestamp() > cursor + 60:
                invalid += 1
                continue
            events[event.event_id] = event
        if len(events) == before:
            partial = True
            break
        cursor = int(min(event.published_at.timestamp() for event in events.values())) - 1
        cap = page == _MAX_PAGES - 1
    if not events:
        raise EventDataUnavailable("未取得可核验事件，不能据此说没有重大事件")
    return MarketEventFeed(
        events=sorted(events.values(), key=lambda event: event.published_at, reverse=True),
        fetched_at=stamp,
        scanned_count=scanned,
        invalid_count=invalid,
        partial=partial or invalid > 0,
        page_limit_reached=cap,
    )
