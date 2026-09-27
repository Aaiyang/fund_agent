"""Market data API schemas: benchmark index series and listed-instrument analysis."""

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

# Weekly bars exist so a three-year window stays a few dozen points, not 750.
MarketPeriod = Literal["day", "week"]


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


class SymbolQuoteResponse(BaseResponse, MarketExternalQuote):
    """GET /markets/{symbol}/quote response.

    Inherits the snapshot's fields verbatim. Units follow the house rule:
    ``change_pct``, ``turnover_rate`` and ``amplitude`` are percent points,
    ``amount`` is in whole currency units and the two market caps are in 亿.
    """


class SymbolHistoryResponse(BaseResponse):
    """GET /markets/{symbol}/history response."""

    symbol: str
    kind: str
    period: MarketPeriod
    range: NavRange
    bars: list[CandleExternalBar]
    total: int
    # Fraction over the returned window, same convention as IndexHistoryResponse.
    period_return: float | None = None


class SymbolIntradayResponse(BaseResponse):
    """GET /markets/{symbol}/intraday response."""

    symbol: str
    kind: str
    trade_date: date | None = None
    prev_close: float | None = None
    points: list[MinuteExternalPoint]
    total: int


class SymbolCompanyResponse(BaseResponse):
    """GET /markets/{symbol}/company response.

    ``company`` is None for the indexes and non-A股 listings that have no record
    in the source, which the screen renders as a hidden section rather than an
    error, so one flaky upstream cannot break the chart above it.
    """

    symbol: str
    company: CompanyExternalProfile | None = None
