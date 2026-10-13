"""基金经理任职与公开披露查询契约，公告日期不等于事件生效日期."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DisclosureCategory = Literal["all", "reports", "major_changes", "personnel", "dividend", "operation", "sales", "other"]


class FundManagerIdentity(BaseModel):
    """页面提供的经理姓名及可核验的经理标识."""

    name: str
    manager_id: str | None = None


class FundManagerPeriod(BaseModel):
    """原始团队管理区间，多人共同管理不拆成个人回报."""

    managers: list[FundManagerIdentity]
    start_date: date
    end_date: date | None = None
    is_current: bool = False
    source_duration: str | None = None


class FundManagerHistoryData(BaseModel):
    """数据源实际展示的历任区间；没有提供业务更新时间."""

    fund_code: str
    periods: list[FundManagerPeriod]
    source_url: str


class FundManagerTenure(BaseModel):
    """同一经理连续区间合并后的任职段，离任后再任保持分段."""

    manager: FundManagerIdentity
    start_date: date
    end_date: date | None = None
    is_current: bool = False


class FundManagersResult(FundManagerHistoryData):
    """保留原始区间及个人任职段，公开截断和缓存时间."""

    tenures: list[FundManagerTenure] = Field(default_factory=list)
    total_periods: int
    total_tenures: int
    truncated: bool = False
    fetched_at: datetime
    from_cache: bool = False
    warnings: list[str] = Field(default_factory=list)


class FundAnnouncement(BaseModel):
    """公告索引，不把标题当成已经读过正文的报告结论."""

    announcement_id: str
    fund_code: str
    title: str
    published_date: date | None = None
    category: str
    source_category: str | None = None
    url: str
    major_change_hints: list[str] = Field(default_factory=list)


class FundAnnouncementPage(BaseModel):
    """上游一页索引，数量/页码与无效条目公开."""

    fund_code: str
    page: int
    page_size: int
    total: int
    items: list[FundAnnouncement]
    invalid_items: int = 0
    missing_items: int = 0


class FundAnnouncementsRequest(BaseModel):
    """按基金代码和类型查询一页，日期/关键词仅筛选当前扫描页."""

    fund_code: str = Field(pattern=r"^[0-9]{6}$")
    category: DisclosureCategory = "all"
    start_date: date | None = None
    end_date: date | None = None
    keyword: str | None = Field(default=None, min_length=1, max_length=80)
    page: int = Field(default=1, ge=1, le=1000)
    limit: int = Field(default=20, ge=1, le=50)
    refresh: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "FundAnnouncementsRequest":
        """拒绝反向区间，不静默颠倒参数."""
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date不能晚于end_date")
        return self


class FundAnnouncementsResult(BaseModel):
    """有界扫描结果；空页或无匹配不能证明基金从未发生重大变更."""

    fund_code: str
    category: DisclosureCategory
    start_date: date | None = None
    end_date: date | None = None
    keyword: str | None = None
    page: int
    page_size: int
    upstream_total: int
    scanned_count: int
    matched_count: int
    invalid_items: int = 0
    missing_items: int = 0
    items: list[FundAnnouncement]
    has_more: bool
    next_page: int | None = None
    content_available: bool = False
    fetched_at: datetime
    from_cache: bool = False
    warnings: list[str] = Field(default_factory=list)
