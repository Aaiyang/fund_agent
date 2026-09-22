"""Fund API request/response schemas."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.base import BaseResponse

NavRange = Literal["1m", "3m", "6m", "1y", "3y", "all"]


class FundSearchItem(BaseModel):
    """One search result row with the caller's relationship flags."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    latest_nav: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None
    is_watchlisted: bool = False
    is_held: bool = False


class FundSearchResponse(BaseResponse):
    """GET /funds/search response."""

    items: list[FundSearchItem]
    total: int


class FundPerformance(BaseModel):
    """Deterministic analytics computed by backend Python (spec 5.2)."""

    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_1y: float | None = None
    return_3y: float | None = None
    return_since_inception: float | None = None
    max_drawdown: float | None = None
    annualized_volatility: float | None = None


class FundDetailResponse(BaseResponse):
    """GET /funds/{fund_code} response — fund overview (spec 3.5.1)."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    company: str | None = None
    manager_name: str | None = None
    inception_date: date | None = None
    asset_size: str | None = None
    benchmark: str | None = None
    latest_nav: float | None = None
    accumulated_nav: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None
    performance: FundPerformance = FundPerformance()
    is_watchlisted: bool = False
    is_held: bool = False
    # Lineage: which source, as of when, and when we last refreshed it (spec 5.6)
    source: str | None = None
    source_as_of: date | None = None
    updated_at: datetime | None = None
    nav_fetched_at: datetime | None = None


class FundNavPoint(BaseModel):
    """One NAV series point for charting."""

    nav_date: date
    unit_nav: float | None = None
    accumulated_nav: float | None = None
    daily_return: float | None = None


class FundNavHistoryResponse(BaseResponse):
    """GET /funds/{fund_code}/nav response."""

    fund_code: str
    range: str | None = None
    points: list[FundNavPoint]
    total: int = 0
    has_more: bool = False


class FundPerformanceResponse(BaseResponse):
    """GET /funds/{fund_code}/performance response."""

    fund_code: str
    performance: FundPerformance


class RelatedSectorsResponse(BaseResponse):
    """GET /funds/{fund_code}/related-sectors response (placeholder)."""

    fund_code: str
    sectors: list[dict[str, object]] = []
    note: str = "related_sectors_not_available_in_mvp"


class FundSyncStatusResponse(BaseResponse):
    """POST /funds/{fund_code}/refresh response."""

    fund_code: str
    queued: bool
    job_id: str | None = None
