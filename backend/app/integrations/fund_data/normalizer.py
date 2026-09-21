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
)

_PERCENT_SUFFIX = re.compile(r"%\s*$")


def to_float(value: Any) -> float | None:
    """Cast a raw cell (number, numeric string, '1.23%', '--') to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None  # NaN guard
    text = _PERCENT_SUFFIX.sub("", str(value).strip().replace(",", ""))
    if not text or text in {"--", "-", "—", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    """Cast a raw date cell (date, datetime, 'YYYY-MM-DD', 'YYYYMMDD') to date."""
    if value is None:
        return None
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
    return None


def _pick(record: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value among candidate column names."""
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip() not in {"", "--", "-", "nan"}:
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

    # "成立日期/规模" cells like "2021-01-01/2.34亿" — keep the date part
    inception_raw = _pick(info, "成立日期", "成立日期/规模", "发行日期")
    inception = to_date(str(inception_raw).split("/")[0]) if inception_raw else None

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
