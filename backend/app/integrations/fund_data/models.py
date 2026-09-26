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
    asset_size: str | None = None


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
    """One stock in a fund's reported holdings, for a given reporting quarter."""

    fund_code: str
    stock_code: str
    stock_name: str | None = None
    weight: float | None = None  # 占净值比例, in percent points
    shares: float | None = None  # 持股数, in 万股 as the source reports it
    market_value: float | None = None  # 持仓市值, in 万元
    quarter: str | None = None  # e.g. "2026年2季度"


class StockExternalQuote(BaseModel):
    """One quote of an individual stock, across A-share / HK / US markets."""

    symbol: str  # source-prefixed instrument id, e.g. sz300570, hk01810, gb_aapl
    name: str | None = None
    price: float | None = None
    change_pct: float | None = None  # percent points, matching fund daily_return
    quote_time: str | None = None  # raw source timestamp; formats differ per market


class IndexExternalQuote(BaseModel):
    """One trading day's close of a benchmark index (fund comparison line)."""

    index_code: str
    trade_date: date
    close: float
