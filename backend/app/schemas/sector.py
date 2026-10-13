"""基金板块关联与板块报价：来源证据和实时行情分开表示."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import BaseResponse
from app.schemas.fund import FundIndustryItem
from app.schemas.market import RealtimeQuoteFreshness

SectorKind = Literal["industry", "concept"]
SectorScope = Literal["industry", "concept", "all"]
SectorBoardKind = Literal["industry", "concept"]
SectorBoardOrder = Literal["desc", "asc"]
# 主力资金净流入与市值要另接数据源（东财在本机不可达），先不放进这个枚举里
# 当假选项：客户端拿到 422 比拿到一个恒为空的字段更难解释。
SectorBoardSort = Literal["change_pct", "amount"]


class SectorItem(BaseModel):
    """数据源真实目录中的板块，不接受模型自造代码."""

    sector_code: str = Field(pattern=r"^BK\d{4,6}$")
    name: str
    sector_type: SectorKind


class SectorCatalog(BaseModel):
    """已完整分页读取的板块目录，获取时间为 naive UTC."""

    items: list[SectorItem]
    fetched_at: datetime


class FundSectorEvidence(BaseModel):
    """基金域服务提供的真实名称与最近披露行业，不查询用户持仓或历史净值."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    industries: list[FundIndustryItem] = Field(default_factory=list)
    report_date: date | None = None


class FundSectorLink(SectorItem):
    """明确区分披露行业名称匹配与待核验的基金名称主题线索."""

    evidence_type: Literal["disclosed_industry", "fund_name_hint"]
    evidence: str
    disclosed_weight: float | None = None  # 占基金净值百分点，只属于披露行业证据
    report_date: date | None = None


class FundSectorsResult(FundSectorEvidence):
    """关联可以为空；不强行给多行业或无证据基金贴单一板块标签."""

    sectors: list[FundSectorLink] = Field(default_factory=list)
    unmatched_industries: list[FundIndustryItem] = Field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False
    unavailable_catalogs: list[SectorKind] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SectorMarketRequest(BaseModel):
    """按已知板块代码、名称或关键词查询，最多返回五个结果."""

    keyword: str = Field(min_length=1, max_length=64)
    sector_type: SectorScope = "all"
    limit: int = Field(default=5, ge=1, le=5)
    refresh: bool = True


class SectorQuote(SectorItem):
    """单个板块的当前可用行情，单项失败不伪造数值."""

    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    quote_time: datetime | None = None
    trade_date: date | None = None
    freshness: RealtimeQuoteFreshness | None = None
    stale: bool = True
    fetched_at: datetime | None = None
    from_cache: bool = False
    error_code: str | None = None


class SectorMarketResult(BaseModel):
    """查询范围、报价日期与缺失项均公开，变化率单位为百分点."""

    keyword: str
    requested_date: date
    timezone: str = "Asia/Shanghai"
    source: str = "eastmoney_sector_quotes"
    change_pct_unit: str = "percentage_points"
    fetched_at_timezone: str = "UTC"
    sectors: list[SectorQuote] = Field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False
    unavailable_catalogs: list[SectorKind] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SectorBoardStock(BaseModel):
    """板块内领涨（跌幅榜时为该板块内相对最强的一只）个股."""

    code: str
    name: str | None = None
    change_pct: float | None = None


class SectorBoardItem(BaseModel):
    """一个板块的当日快照；缺数就是 None，不补成 0 也不猜涨跌方向."""

    code: str
    name: str
    sector_type: SectorBoardKind
    stock_count: int | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    amount: float | None = None
    leading_stock: SectorBoardStock | None = None


class SectorBoardResponse(BaseResponse):
    """板块涨跌榜.

    上游不带报价时间戳，所以 `fetched_at` 只是我们抓取的时刻，不能当开市证明；
    `quote_time_verified` 恒为 False，并由 warnings 说明这一层限制。
    """

    source: str
    sector_type: SectorBoardKind
    order: SectorBoardOrder
    sort: SectorBoardSort
    change_pct_unit: str = "percentage_points"
    fetched_at: datetime
    quote_time_verified: bool = False
    items: list[SectorBoardItem] = Field(default_factory=list)
    total_available: int = 0
    warnings: list[str] = Field(default_factory=list)
