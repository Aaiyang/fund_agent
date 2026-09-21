"""Watchlist API schemas."""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.base import BaseResponse


class WatchlistFundItem(BaseModel):
    """One watchlisted fund with market data and relationship flags."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    latest_nav: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None
    is_held: bool = False
    is_updated: bool = False
    sort_order: int = 0
    groups: list[str] = []
    group_ids: list[int] = []


class WatchlistResponse(BaseResponse):
    """GET /watchlist response."""

    items: list[WatchlistFundItem]
    total: int


class WatchlistAddRequest(BaseModel):
    """POST /watchlist request."""

    fund_code: str = Field(min_length=5, max_length=12)
    group_ids: list[int] = Field(default_factory=list)


class WatchlistUpdateRequest(BaseModel):
    """PATCH /watchlist/{fund_code} request."""

    sort_order: int | None = None
    group_ids: list[int] | None = None


class WatchlistGroupItem(BaseModel):
    """One watchlist group."""

    id: int
    name: str
    sort_order: int
    fund_count: int = 0


class WatchlistGroupsResponse(BaseResponse):
    """GET /watchlist/groups response."""

    items: list[WatchlistGroupItem]
    total: int


class WatchlistGroupCreateRequest(BaseModel):
    """POST /watchlist/groups request."""

    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0


class WatchlistGroupUpdateRequest(BaseModel):
    """PATCH /watchlist/groups/{group_id} request."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    sort_order: int | None = None
    fund_codes: list[str] | None = Field(
        default=None,
        description="整组覆盖：分组内基金代码及顺序（未在自选内的代码会被忽略）",
    )
