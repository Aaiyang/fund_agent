"""Normalizers converting raw AKShare payloads into internal domain models.

All parsing is defensive: third-party column names and value formats change
between AKShare versions, so every field is optional and every cast tolerant.
"""

import re
from datetime import date, datetime
from typing import Any

from app.core.logging import logger
from app.integrations.fund_data.models import (
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
    IndexExternalQuote,
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
