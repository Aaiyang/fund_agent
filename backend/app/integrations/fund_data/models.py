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


class FundExternalIndustry(BaseModel):
    """One industry's share of a fund's net asset value, per disclosure."""

    fund_code: str
    industry: str
    weight: float | None = None  # 占净值比例, percent points
    market_value: float | None = None
    as_of: date | None = None  # 截止时间 of the reporting period


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


class MarketExternalQuote(BaseModel):
    """Realtime snapshot of one listed instrument, across A股 / 港股 / 美股 / 指数.

    Amounts are in the instrument's own currency; ``amount`` is in base units
    (元/港元/美元) while the market-cap pair stays in 亿 as the source reports it.
    """

    symbol: str  # canonical Tencent symbol: sh600519, sz300570, hk01810, usAAPL.OQ, sh000001
    listing_code: str | None = None  # the source's own code, e.g. AAPL.OQ — bars need that suffix
    kind: str  # "stock" | "index"
    name: str | None = None
    currency: str | None = None  # CNY / HKD / USD
    price: float | None = None
    prev_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    change: float | None = None  # absolute price move
    change_pct: float | None = None  # percent points, matching fund daily_return
    volume: float | None = None  # raw source unit; see volume_unit
    volume_unit: str | None = None  # 手 for A股/指数, 股 for 港股/美股
    amount: float | None = None
    turnover_rate: float | None = None  # 换手率, percent points
    amplitude: float | None = None  # 振幅, percent points
    pe: float | None = None  # 市盈率, stocks only
    pb: float | None = None  # 市净率, A股 only
    float_market_cap: float | None = None  # 流通市值, 亿
    total_market_cap: float | None = None  # 总市值, 亿
    week52_high: float | None = None
    week52_low: float | None = None
    quote_time: str | None = None  # normalized to "YYYY-MM-DD HH:MM:SS"


class CandleExternalBar(BaseModel):
    """One OHLCV bar; ``volume`` keeps the quote's own unit."""

    trade_date: date
    open: float
    close: float
    high: float
    low: float
    volume: float | None = None


class MinuteExternalPoint(BaseModel):
    """One minute of a trading session.

    ``volume`` and ``amount`` are per-minute, derived from the source's running
    totals; ``average_price`` is only meaningful for stocks. ``trade_date`` stays
    None for a single session and is filled for the five-day series, where the
    points span several days.
    """

    time: str  # "HH:MM"
    price: float
    volume: float | None = None
    amount: float | None = None
    average_price: float | None = None
    trade_date: date | None = None


class MinuteExternalSeries(BaseModel):
    """A minute line plus the two numbers its axis needs."""

    trade_date: date | None = None  # the newest session in the series
    prev_close: float | None = None  # the flat reference line 分时 charts draw
    points: list[MinuteExternalPoint] = []


class CompanyExternalProfile(BaseModel):
    """Listed company master data (A股 only; other markets return no profile)."""

    symbol: str
    name: str | None = None
    industry: str | None = None
    region: str | None = None
    list_date: date | None = None
    main_business: str | None = None
    description: str | None = None
    employees: float | None = None
    chairman: str | None = None
    concepts: list[str] = []
