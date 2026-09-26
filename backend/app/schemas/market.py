"""Benchmark index API schemas (fund-detail comparison line)."""

from datetime import date

from pydantic import BaseModel

from app.schemas.base import BaseResponse
from app.schemas.fund import NavRange


class IndexCatalogItem(BaseModel):
    """One selectable benchmark."""

    index_code: str
    name: str


class IndexCatalogResponse(BaseResponse):
    """GET /indexes response."""

    items: list[IndexCatalogItem]
    total: int


class IndexPoint(BaseModel):
    """One trading day's closing level."""

    trade_date: date
    close: float


class IndexQuoteItem(BaseModel):
    """One index's latest close and its day change."""

    index_code: str
    name: str
    close: float | None = None
    # Percent points (2.2 = +2.2%), like the fund `daily_return` column, so the
    # same formatter handles funds and indexes on the tape.
    change_pct: float | None = None
    trade_date: date | None = None


class IndexQuotesResponse(BaseResponse):
    """GET /indexes/quotes response."""

    items: list[IndexQuoteItem]
    total: int


class IndexHistoryResponse(BaseResponse):
    """GET /indexes/{index_code}/history response."""

    index_code: str
    name: str
    range: NavRange | None = None
    points: list[IndexPoint]
    # Fraction over the window (0.022 = +2.2%), matching FundPerformance's
    # `return_*` fields — unlike the watchlist `*_return` fields, which are
    # already percent points.
    period_return: float | None = None
