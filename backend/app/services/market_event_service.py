"""公开事件筛选及短期可核验引用，不存任何私有持仓数据."""

from collections import OrderedDict
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.analytics.event_links import classify_event, event_fingerprint
from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.integrations.fund_data.event_client import fetch_event_feed
from app.schemas.market_event import MarketEvent, MarketEventFeed, MarketEventsRequest, MarketEventsResult
from app.utils.clock import business_now, utc_now

_FEED_TTL = 60
_REFERENCE_TTL = 12 * 3600
_MAX_REFERENCES = 1000


class EventReference(BaseModel):
    """公开事件的已获取快照与UTC保存时间."""

    event: MarketEvent
    stored_at: datetime


def valid_event(event: MarketEvent) -> bool:
    """核验来源及内容指纹，不能将模型自造正文当已检索事件."""
    categories, topics, factors = classify_event(event.title + " " + event.excerpt)
    return (
        event.published_at.tzinfo is not None
        and event.source == "cls_telegraph"
        and (event.categories, event.topics, event.factors) == (categories, topics, factors)
        and event.source_id.isascii()
        and event.source_id.isdigit()
        and event.source_url == "https://www.cls.cn/detail/" + event.source_id
        and event.event_id
        == event_fingerprint(event.source_id, event.title, event.excerpt, event.published_at.isoformat())
    )


class MarketEventService:
    """来源窗口成功缓存与公共事件引用，私有关联结果从不进入此缓存."""

    def __init__(self) -> None:
        """内存引用为缓存故障兜底，有TTL及总量上限."""
        self._references: OrderedDict[str, EventReference] = OrderedDict()

    async def _feed(self, refresh: bool) -> tuple[MarketEventFeed, bool]:
        key = cache_key("market_event_feed:v1")
        if not refresh:
            try:
                raw = await cache_service.get(key)
                if raw:
                    feed = MarketEventFeed.model_validate_json(raw)
                    age = (utc_now() - feed.fetched_at).total_seconds() if feed.fetched_at.tzinfo is None else -1
                    if (
                        0 <= age < _FEED_TTL
                        and feed.events
                        and not feed.partial
                        and all(valid_event(event) for event in feed.events)
                    ):
                        return feed, True
            except Exception:
                logger.exception("market_event_feed_cache_read_failed")
        feed = await fetch_event_feed()
        if not feed.partial and feed.events:
            try:
                await cache_service.set(key, feed.model_dump_json(), ttl=_FEED_TTL)
            except Exception:
                logger.exception("market_event_feed_cache_write_failed")
        return feed, False

    async def query(self, request: MarketEventsRequest) -> MarketEventsResult:
        """范围、时间和关键词本地筛选，不向资讯来源发送任何对话查询词."""
        feed, from_cache = await self._feed(request.refresh)
        now = business_now()
        beginning = now - timedelta(hours=request.lookback_hours)
        events = [
            event
            for event in feed.events
            if beginning <= event.published_at <= now
            and (request.scope == "all" or request.scope in event.categories)
            and (not request.important_only or event.source_priority in {"A", "B"})
            and (not request.keyword or request.keyword.strip().casefold() in (event.title + event.excerpt).casefold())
        ]
        warnings = [
            "事件来自财联社公开报道，非官方原始公告或独立核验结论；发布时间不是发生时间或生效时间。",
            "仅扫描来源最近最多100条，不能保证覆盖请求时段全部宏观、行业或市场事件；空匹配不代表无重大事件。",
            "重点仅指来源A/B标记，分类/主题/宏观标签来自有限文本规则，可能漏判或误判。",
        ]
        if feed.partial:
            warnings.append("来源扫描不完整或部分条目无效，当前为部分结果，未缓存整批响应。")
        if len(events) > request.limit:
            warnings.append("匹配结果已截断，可增大limit至30或调整范围；不能称为全部事件。")
        selected = events[: request.limit]
        for event in selected:
            ref = EventReference(event=event.model_copy(deep=True), stored_at=utc_now())
            self._references[event.event_id] = ref
            self._references.move_to_end(event.event_id)
            while len(self._references) > _MAX_REFERENCES:
                self._references.popitem(last=False)
            try:
                await cache_service.set(
                    cache_key("market_event_ref:v1", event.event_id), ref.model_dump_json(), ttl=_REFERENCE_TTL
                )
            except Exception:
                logger.exception("market_event_reference_cache_write_failed")
        times = [event.published_at for event in feed.events]
        return MarketEventsResult(
            **feed.model_dump(exclude={"events"}),
            events=selected,
            scope=request.scope,
            requested_from=beginning,
            requested_to=now,
            coverage_from=min(times) if times else None,
            coverage_to=max(times) if times else None,
            matched_count=len(events),
            truncated=len(events) > request.limit,
            from_cache=from_cache,
            warnings=warnings,
        )

    async def resolve(self, event_ids: list[str]) -> tuple[list[MarketEvent], list[str]]:
        """只接受此前查询保存的未过期引用；缺失不从模型文字补出事件."""
        events, missing = [], []
        for event_id in dict.fromkeys(event_ids):
            ref = self._references.get(event_id)
            if ref is None:
                try:
                    raw = await cache_service.get(cache_key("market_event_ref:v1", event_id))
                    ref = EventReference.model_validate_json(raw) if raw else None
                except Exception:
                    logger.exception("market_event_reference_cache_read_failed")
            if ref is not None:
                # 时间解析走Pydantic，损坏的保存时间作为缺失而非跨用户可用数据。
                try:
                    age = (utc_now() - ref.stored_at).total_seconds() if ref.stored_at.tzinfo is None else -1
                    if 0 <= age < _REFERENCE_TTL and ref.event.event_id == event_id and valid_event(ref.event):
                        events.append(ref.event.model_copy(deep=True))
                        continue
                except Exception:
                    logger.exception("market_event_reference_invalid")
            self._references.pop(event_id, None)
            missing.append(event_id)
        return events, missing


market_event_service = MarketEventService()
