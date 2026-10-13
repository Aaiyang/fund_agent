"""公开事件与私有持仓关联契约，潜在关联不是收益预测."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

EventScope = Literal["all", "macro", "industry", "market"]
EventId = Annotated[str, Field(pattern=r"^cls_[0-9]{1,16}_[0-9a-f]{12}$")]


class MarketEvent(BaseModel):
    """来源报道快照，不代表事件已被独立证实或已经生效."""

    event_id: EventId
    source_id: str
    title: str
    excerpt: str
    published_at: datetime
    source: str = "cls_telegraph"
    source_url: str
    source_priority: Literal["A", "B", "C", "unknown"]
    categories: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    factors: list[str] = Field(default_factory=list)


class MarketEventFeed(BaseModel):
    """有界来源窗口，缺页和解析缺数明确保留."""

    events: list[MarketEvent]
    fetched_at: datetime
    scanned_count: int = 0
    invalid_count: int = 0
    partial: bool = False
    page_limit_reached: bool = False


class MarketEventsRequest(BaseModel):
    """筛选在本地执行，查询词不会传给公开来源."""

    model_config = ConfigDict(extra="forbid")
    scope: EventScope = "all"
    lookback_hours: int = Field(default=24, ge=1, le=168)
    keyword: str | None = Field(default=None, min_length=1, max_length=80)
    important_only: bool = True
    limit: int = Field(default=20, ge=1, le=30)
    refresh: bool = False


class MarketEventsResult(MarketEventFeed):
    """筛选结果及实际扫描窗口，发布时间不充当发生/生效时间."""

    scope: EventScope
    requested_from: datetime
    requested_to: datetime
    coverage_from: datetime | None = None
    coverage_to: datetime | None = None
    matched_count: int
    truncated: bool = False
    from_cache: bool = False
    warnings: list[str] = Field(default_factory=list)


class EventPortfolioLinkRequest(BaseModel):
    """用户身份与持仓原文不可由模型提交，只接收来源快照ID."""

    model_config = ConfigDict(extra="forbid")
    event_ids: list[EventId] = Field(
        min_length=1, max_length=5, description="get_market_events返回的1–5个event_id，不接受自编事件正文或URL"
    )
    account_id: int | None = Field(default=None, ge=1, description="可选账户，必须属于当前用户；默认全部账户")
    position_limit: int = Field(default=20, ge=1, le=50, description="最多检查的持仓行数，按市值从大到小，默认20")


class EventPositionLink(BaseModel):
    """记录关联依据而非确定的因果影响，方向固定未知."""

    event_id: str
    fund_code: str
    fund_name: str | None = None
    account_id: int
    basis: Literal["disclosed_industry", "fund_name_hint", "macro_context", "market_context"]
    evidence: str
    disclosure_date: str | None = None
    matched_topics: list[str] = Field(default_factory=list)
    possible_channel: str
    impact_direction: Literal["unknown"] = "unknown"


class EventPortfolioLinksResult(BaseModel):
    """不缓存私有分析，未发现匹配不等于事件不影响持仓."""

    events: list[MarketEvent]
    account_id: int | None = None
    total_positions: int
    checked_positions: int
    skipped_positions: int
    unavailable_funds: list[str] = Field(default_factory=list)
    associations: list[EventPositionLink]
    total_associations: int
    truncated: bool = False
    holdings_checked_at: datetime
    warnings: list[str] = Field(default_factory=list)
