"""基金 API 的请求与响应 schema."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.base import BaseResponse

NavRange = Literal["1m", "3m", "6m", "1y", "3y", "all"]


class FundSearchItem(BaseModel):
    """一条搜索结果，附调用方与它的关系标记（自选/持有）."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    latest_nav: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None
    is_watchlisted: bool = False
    is_held: bool = False


class FundSearchResponse(BaseResponse):
    """GET /funds/search 响应体."""

    items: list[FundSearchItem]
    total: int


class FundPerformance(BaseModel):
    """由后端 Python 确定性算出的业绩指标（spec 5.2）."""

    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_1y: float | None = None
    return_3y: float | None = None
    return_since_inception: float | None = None
    max_drawdown: float | None = None
    annualized_volatility: float | None = None


class FundDetailResponse(BaseResponse):
    """GET /funds/{fund_code} 响应——基金概览（spec 3.5.1）."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    company: str | None = None
    manager_name: str | None = None
    inception_date: date | None = None
    asset_size: str | None = None
    latest_nav: float | None = None
    accumulated_nav: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None
    performance: FundPerformance = FundPerformance()
    is_watchlisted: bool = False
    is_held: bool = False
    # 数据血缘：出自哪个数据源、数据截至何时、我们上次刷新是何时（spec 5.6）
    source: str | None = None
    source_as_of: date | None = None
    updated_at: datetime | None = None
    nav_fetched_at: datetime | None = None


class FundNavPoint(BaseModel):
    """净值序列里的一个点，用于画图."""

    nav_date: date
    unit_nav: float | None = None
    accumulated_nav: float | None = None
    daily_return: float | None = None


class FundNavHistoryResponse(BaseResponse):
    """GET /funds/{fund_code}/nav 响应体."""

    fund_code: str
    range: str | None = None
    points: list[FundNavPoint]
    total: int = 0
    has_more: bool = False


class FundHoldingItem(BaseModel):
    """一条披露持仓，带行情报价和较上期变动."""

    stock_code: str
    # 给行情分析页用的带市场前缀 symbol：披露表没有市场列，所以这里直接发布
    # 行情源那套形状推断的结果，不让客户端再推一遍。
    symbol: str | None = None
    stock_name: str | None = None
    weight: float | None = None  # 占净值比例，单位百分点
    weight_change: float | None = None  # 较上期变动，单位百分点
    is_new: bool = False  # 上一期披露里没有这只票
    price: float | None = None
    change_pct: float | None = None  # 盘中取实时涨跌，收盘后取最近收盘价
    quote_time: str | None = None  # 上游原始时间戳，格式因市场而异


class FundIndustryItem(BaseModel):
    """某行业占该基金的份额，取自同一期披露."""

    industry: str
    weight: float | None = None  # 占净值比例，单位百分点


class FundHoldingsResponse(BaseResponse):
    """GET /funds/{fund_code}/holdings 响应（按披露权重取前十）."""

    fund_code: str
    quarter: str | None = None
    previous_quarter: str | None = None
    items: list[FundHoldingItem] = []
    industries: list[FundIndustryItem] = []
    industries_as_of: date | None = None


class FundPerformanceResponse(BaseResponse):
    """GET /funds/{fund_code}/performance 响应体."""

    fund_code: str
    performance: FundPerformance


class RelatedSectorsResponse(BaseResponse):
    """GET /funds/{fund_code}/related-sectors 响应（占位实现）."""

    fund_code: str
    sectors: list[dict[str, object]] = []
    note: str = "related_sectors_not_available_in_mvp"


class FundSyncStatusResponse(BaseResponse):
    """POST /funds/{fund_code}/refresh 响应体."""

    fund_code: str
    queued: bool
    job_id: str | None = None


class FundNavRefreshResponse(BaseResponse):
    """POST /funds/refresh-latest 响应体.

    客户端唯一需要分支的字段是 `status`，除 `unavailable` 之外都属正常结果而非
    错误：全量表里没有的基金会被逐个单独入队补刷，同一用户已有刷新在跑时报
    `throttled`。那几个计数只是给前端看的结果播报。
    """

    status: Literal["ok", "partial", "throttled", "deferred", "unavailable"] = "ok"
    requested: int = 0
    updated: int = 0
    missing: list[str] = []
    nav_date: date | None = None
