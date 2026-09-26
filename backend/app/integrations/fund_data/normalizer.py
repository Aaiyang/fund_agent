"""Normalizers converting raw AKShare payloads into internal domain models.

All parsing is defensive: third-party column names and value formats change
between AKShare versions, so every field is optional and every cast tolerant.
"""

import re
from datetime import date, datetime
from typing import Any

from app.core.logging import logger
from app.integrations.fund_data.models import (
    FundExternalHolding,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
    IndexExternalQuote,
    StockExternalQuote,
)

_PERCENT_SUFFIX = re.compile(r"%\s*$")


def to_float(value: Any) -> float | None:
    """Cast a raw cell (number, numeric string, '1.23%', '--') to float."""
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _PERCENT_SUFFIX.sub("", str(value).strip().replace(",", ""))
    if not text or text in _MISSING_TOKENS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    """Cast a raw date cell (date, datetime, 'YYYY-MM-DD', 'YYYYMMDD') to date.

    Anything unparseable becomes None: pandas hands us NaT for missing dates,
    and touching a NaT raises rather than returning None.
    """
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return None


# Sentinels AKShare/pandas use for "no value"; NaT reaches us as a str() of 'NaT'
# and NaN as a float that is not equal to itself.
_MISSING_TOKENS = {"", "--", "-", "—", "None", "nan", "NaN", "NaT", "nat"}


def _is_missing(value: Any) -> bool:
    """True for None, NaN, NaT and the placeholder strings AKShare emits."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    if str(value).strip() in _MISSING_TOKENS:
        return True
    # pandas NaT is datetime-like but explodes on any real use
    return type(value).__name__ == "NaTType"


def _pick(record: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value among candidate column names."""
    for key in keys:
        value = record.get(key)
        if not _is_missing(value):
            return value
    return None


def normalize_fund_record(record: dict[str, Any]) -> FundExternalRecord | None:
    """Normalize one search/rank row into a FundExternalRecord."""
    fund_code = _pick(record, "基金代码", "fund_code", "代码")
    fund_name = _pick(record, "基金简称", "基金全称", "fund_name", "名称")
    if not fund_code:
        return None
    return FundExternalRecord(
        fund_code=str(fund_code).strip().zfill(6),
        fund_name=str(fund_name or "").strip(),
        fund_type=str(_pick(record, "基金类型", "fund_type")).strip() or None if _pick(record, "基金类型") else None,
        latest_nav=to_float(_pick(record, "单位净值", "最新净值", "nav")),
        nav_date=to_date(_pick(record, "日期", "净值日期", "nav_date")),
        daily_return=to_float(_pick(record, "日增长率", "日涨跌幅", "daily_return")),
    )


def _text(info: dict[str, Any], limit: int, *keys: str) -> str | None:
    """First usable value among the candidate keys, trimmed to `limit` characters."""
    value = _pick(info, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def normalize_profile_rows(rows: list[dict[str, Any]], fund_code: str) -> FundExternalProfile | None:
    """Normalize fund_individual_basic_info_xq-style item/value rows."""
    if not rows:
        return None
    info: dict[str, Any] = {}
    for row in rows:
        key = str(_pick(row, "item", "项目", "选项") or "").strip()
        if key:
            info[key] = _pick(row, "value", "值", "数值")

    fund_name = str(_pick(info, "基金简称", "基金全称") or "").strip()
    if not fund_name:
        logger.debug("fund_profile_name_missing", fund_code=fund_code)
        return None

    # AKShare renamed this cell across versions: 成立日期 / 成立日期/规模 / 成立时间
    # all appear in the wild, and a missed key silently yields None.
    inception_raw = _pick(info, "成立日期", "成立日期/规模", "成立时间", "发行日期")
    inception = None
    if inception_raw:
        text = str(inception_raw).strip()
        # "2021-01-01/2.34亿" carries the size after the date; slash-formatted
        # dates must not be split, so the whole value is tried first.
        inception = to_date(text) or to_date(text.split("/")[0])

    return FundExternalProfile(
        fund_code=fund_code,
        fund_name=fund_name,
        fund_type=str(_pick(info, "基金类型") or "").strip() or None,
        company=str(_pick(info, "基金管理人", "基金公司") or "").strip() or None,
        manager_name=str(_pick(info, "基金经理") or "").strip() or None,
        inception_date=inception,
        asset_size=_text(info, 50, "最新规模", "基金规模", "规模"),
    )


def normalize_nav_rows(
    unit_rows: list[dict[str, Any]],
    accumulated_rows: list[dict[str, Any]],
    fund_code: str,
) -> list[FundExternalNav]:
    """Merge unit-NAV and accumulated-NAV rows keyed by NAV date."""
    accumulated_by_date = {
        nav_date: to_float(_pick(row, "累计净值"))
        for row in accumulated_rows
        if (nav_date := to_date(_pick(row, "净值日期", "日期"))) is not None
    }

    navs: list[FundExternalNav] = []
    for row in unit_rows:
        nav_date = to_date(_pick(row, "净值日期", "日期"))
        if nav_date is None:
            continue
        navs.append(
            FundExternalNav(
                fund_code=fund_code,
                nav_date=nav_date,
                unit_nav=to_float(_pick(row, "单位净值")),
                accumulated_nav=accumulated_by_date.get(nav_date),
                daily_return=to_float(_pick(row, "日增长率")),
            )
        )
    navs.sort(key=lambda nav: nav.nav_date, reverse=True)
    return navs


def normalize_index_rows(rows: list[dict[str, Any]], index_code: str) -> list[IndexExternalQuote]:
    """Convert an index daily frame into ascending (date, close) quotes.

    AKShare's index endpoints disagree on column naming between versions and
    sources (Sina is lowercase English, Eastmoney is Chinese), so both
    spellings are accepted and unusable rows are dropped.
    """
    quotes: list[IndexExternalQuote] = []
    for row in rows:
        trade_date = to_date(_pick(row, "date", "日期", "trade_date"))
        close = to_float(_pick(row, "close", "收盘", "close_price"))
        if trade_date is None or close is None or close <= 0:
            continue
        quotes.append(IndexExternalQuote(index_code=index_code, trade_date=trade_date, close=close))
    quotes.sort(key=lambda quote: quote.trade_date)
    return quotes


_QUARTER_PATTERN = re.compile(r"(\d{4})年(\d)季度")


def parse_quarter(label: Any) -> tuple[int, int] | None:
    """Order key for a reporting period like ``2026年2季度股票投资明细``."""
    if label is None:
        return None
    match = _QUARTER_PATTERN.search(str(label))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def normalize_holding_rows(rows: list[dict[str, Any]], fund_code: str) -> list[FundExternalHolding]:
    """Convert ``fund_portfolio_hold_em`` rows into holdings with their quarter."""
    holdings: list[FundExternalHolding] = []
    for row in rows:
        stock_code = _pick(row, "股票代码", "证券代码", "stock_code")
        if stock_code is None:
            continue
        quarter_label = _pick(row, "季度", "period")
        holdings.append(
            FundExternalHolding(
                fund_code=fund_code,
                stock_code=str(stock_code).strip(),
                stock_name=str(_pick(row, "股票名称", "证券简称", "stock_name") or "").strip() or None,
                weight=to_float(_pick(row, "占净值比例", "占净值比例(%)", "weight")),
                shares=to_float(_pick(row, "持股数", "持仓数量")),
                market_value=to_float(_pick(row, "持仓市值", "市值")),
                quarter=str(quarter_label).strip() if quarter_label else None,
            )
        )
    return holdings


def sina_symbol(stock_code: str) -> str | None:
    """Map a holding's code to its quote symbol; markets are encoded in the shape.

    The holdings table carries no market column, so a 6-digit code is a Chinese
    listing (5/6/9 Shanghai, otherwise Shenzhen), a 5-digit one is Hong Kong, and
    a lettered ticker is a US listing.
    """
    code = stock_code.strip()
    if code.isdigit():
        if len(code) == 6:
            return ("sh" if code[0] in "569" else "sz") + code
        if len(code) == 5:
            return "hk" + code
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,9}", code):
        return "gb_" + code.lower()
    return None


_SINA_LINE = re.compile(r'var hq_str_(?P<symbol>\w+)="(?P<body>[^"]*)"')


def parse_sina_quotes(payload: str) -> list[StockExternalQuote]:
    """Parse the batched quote reply; each market has its own field layout."""
    quotes: list[StockExternalQuote] = []
    for match in _SINA_LINE.finditer(payload):
        symbol = match.group("symbol")
        fields = match.group("body").split(",")
        if len(fields) < 4 or not fields[0]:
            continue
        if symbol.startswith("gb_"):
            # 名称,现价,涨跌幅,时间,涨跌额,昨收,开盘,最高,最低,...
            quotes.append(
                StockExternalQuote(
                    symbol=symbol,
                    name=fields[0],
                    price=to_float(fields[1]),
                    change_pct=to_float(fields[2]),
                    quote_time=fields[3] or None,
                )
            )
        elif symbol.startswith("hk"):
            # 英文名,名称,昨收,开盘,最高,最低,现价,涨跌额,涨跌幅,...,日期,时间
            quotes.append(
                StockExternalQuote(
                    symbol=symbol,
                    name=fields[1],
                    price=to_float(fields[6]),
                    change_pct=to_float(fields[8]),
                    quote_time=" ".join(fields[-2:]) if len(fields) > 2 else None,
                )
            )
        else:
            # A股: 名称,今开,昨收,现价,最高,最低,...,日期(30),时间(31)
            previous_close = to_float(fields[2])
            price = to_float(fields[3])
            change_pct = None
            if previous_close and price is not None:
                change_pct = round((price - previous_close) / previous_close * 100, 4)
            quotes.append(
                StockExternalQuote(
                    symbol=symbol,
                    name=fields[0],
                    price=price,
                    change_pct=change_pct,
                    quote_time=" ".join(fields[30:32]) if len(fields) > 31 else None,
                )
            )
    return quotes
