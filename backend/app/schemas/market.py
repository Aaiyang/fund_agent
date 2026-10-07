"""行情数据 API 的 schema：基准指数序列与上市标的分析."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.integrations.fund_data.models import (
    CandleExternalBar,
    CompanyExternalProfile,
    MarketExternalQuote,
    MinuteExternalPoint,
)
from app.schemas.base import BaseResponse
from app.schemas.fund import NavRange

# 设周线与月线，是为了让长区间停在几十个点上，而不是几百个。
# 上游数据源只有在请求带复权参数时才返回月 K。
MarketPeriod = Literal["day", "week", "month"]
# 分时线能覆盖的交易日：当天，或把最近 5 天拼接起来。
# 这个别名只给响应模型用；查询参数不能写成 Literal，因为 FastAPI 交过来的是
# 文本，pydantic 不会把它放宽成 int。
MarketDays = Literal[1, 5]


class IndexCatalogItem(BaseModel):
    """一个可供选择的业绩比较基准."""

    index_code: str
    name: str


class IndexCatalogResponse(BaseResponse):
    """GET /indexes 响应体."""

    items: list[IndexCatalogItem]
    total: int


class IndexPoint(BaseModel):
    """某个交易日的指数收盘点位."""

    trade_date: date
    close: float


class IndexQuoteItem(BaseModel):
    """一只指数的最新收盘点位与当日涨跌."""

    index_code: str
    name: str
    close: float | None = None
    # 单位百分点（2.2 即 +2.2%），和基金的 `daily_return` 列一致，
    # 这样首页行情条上基金与指数能共用同一个格式化函数。
    change_pct: float | None = None
    trade_date: date | None = None


class IndexQuotesResponse(BaseResponse):
    """GET /indexes/quotes 响应体."""

    items: list[IndexQuoteItem]
    total: int


class IndexHistoryResponse(BaseResponse):
    """GET /indexes/{index_code}/history 响应体."""

    index_code: str
    name: str
    range: NavRange | None = None
    points: list[IndexPoint]
    # 区间收益是小数比例（0.022 即 +2.2%），与 FundPerformance 的 `return_*`
    # 字段同口径——自选列表里的 `*_return` 不同，那些已经是百分点。
    period_return: float | None = None


class SymbolQuoteResponse(BaseResponse, MarketExternalQuote):
    """GET /markets/{symbol}/quote 响应体.

    快照字段原样继承。单位遵守本项目的统一口径：``change_pct``、
    ``turnover_rate``、``amplitude`` 是百分点，``amount`` 是元，
    两个市值字段单位是亿。
    """


class SymbolHistoryResponse(BaseResponse):
    """GET /markets/{symbol}/history 响应体."""

    symbol: str
    kind: str
    period: MarketPeriod
    range: NavRange
    bars: list[CandleExternalBar]
    total: int
    # 返回区间的收益比例，口径与 IndexHistoryResponse 相同。
    period_return: float | None = None


class SymbolIntradayResponse(BaseResponse):
    """GET /markets/{symbol}/intraday 响应体."""

    symbol: str
    kind: str
    days: MarketDays
    trade_date: date | None = None
    prev_close: float | None = None
    points: list[MinuteExternalPoint]
    total: int


class SymbolCompanyResponse(BaseResponse):
    """GET /markets/{symbol}/company 响应体.

    指数以及上游没有记录的 A 股以外标的，``company`` 为 None——页面把这种情况
    渲染成隐藏整个板块而不是报错，于是单个上游抖动拖不垮上方的图表。
    """

    symbol: str
    company: CompanyExternalProfile | None = None
