"""Domain models returned by fund data providers.

Providers must convert their raw payloads into these internal models —
third-party field structures are never passed through to the frontend
(MVP spec 5.5).
"""

from datetime import date

from pydantic import BaseModel


class FundExternalRecord(BaseModel):
    """A fund surfaced by search: code, name, and latest public NAV."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    latest_nav: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None


class FundExternalProfile(BaseModel):
    """Fund master data: identity, type, company, manager, inception."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    company: str | None = None
    manager_name: str | None = None
    inception_date: date | None = None


class FundExternalNav(BaseModel):
    """One NAV data point (unit + accumulated) for a fund."""

    fund_code: str
    nav_date: date
    unit_nav: float | None = None
    accumulated_nav: float | None = None
    daily_return: float | None = None


class FundExternalManager(BaseModel):
    """Fund manager basic information."""

    fund_code: str
    manager_name: str | None = None


class FundExternalHolding(BaseModel):
    """A stock holding inside a fund portfolio (future enhancement)."""

    fund_code: str
    stock_code: str | None = None
    stock_name: str | None = None
    weight: float | None = None


class IndexExternalQuote(BaseModel):
    """One trading day's close of a benchmark index (fund comparison line)."""

    index_code: str
    trade_date: date
    close: float
