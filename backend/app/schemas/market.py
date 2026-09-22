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


class IndexHistoryResponse(BaseResponse):
    """GET /indexes/{index_code}/history response."""

    index_code: str
    name: str
    range: NavRange | None = None
    points: list[IndexPoint]
    period_return: float | None = None
