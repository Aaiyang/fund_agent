"""Clock helpers — the single place where this app decides what "now" means.

Every timestamp column in the schema is `timestamp without time zone`, so a
tz-aware value is rejected by asyncpg and a naive *local* value silently drifts
against the rest of the table. Writes therefore all use :func:`utc_now`.

Calendar dates (`trade_date`, NAV dates) are business days on the Chinese fund
market, so they use ``FUND_BUSINESS_TZ`` rather than whatever zone the host
happens to run in.
"""

import calendar
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import settings

# Chart ranges (spec 3.5.3): months back from a reference date, None = all time
NAV_RANGE_MONTHS: dict[str, int | None] = {"1m": 1, "3m": 3, "6m": 6, "1y": 12, "3y": 36, "all": None}


def utc_now() -> datetime:
    """Return a naive UTC timestamp, matching the schema's column types."""
    return datetime.now(UTC).replace(tzinfo=None)


def business_today() -> date:
    """Return today's date on the fund market calendar."""
    return datetime.now(ZoneInfo(settings.FUND_BUSINESS_TZ)).date()


def business_now() -> datetime:
    """Current wall-clock time where the fund market runs.

    For display and prompt context only. Host-local time would tell the model
    the wrong hour (and therefore the wrong trading session), and this value
    must never be written to a timestamp column — use :func:`utc_now` for that.
    """
    return datetime.now(ZoneInfo(settings.FUND_BUSINESS_TZ))


def business_close_utc(trade_date: date) -> datetime:
    """Naive UTC instant of a business day's market close.

    When only the calendar date survives, midnight in the business zone is
    16:00 UTC the previous day, so comparing that raw date against a UTC cutoff
    would read up to 8 hours staler than it is.
    """
    close = datetime.combine(trade_date, time(15, 0), tzinfo=ZoneInfo(settings.FUND_BUSINESS_TZ))
    return close.astimezone(UTC).replace(tzinfo=None)


def trading_session_label(now: datetime | None = None) -> str:
    """A股交易时段标签：盘前/盘中（上午）/午间休市/盘中（下午）/已收盘/休市.

    用于上下文 Dynamic Tail（KV Cache 友好：一天只变化数次，且比秒级
    时间对模型更有用）。法定节假日未接入日历，会显示为正常交易日，
    模型可结合行情数据自行修正。
    """
    moment = now or datetime.now(ZoneInfo(settings.FUND_BUSINESS_TZ))
    if moment.weekday() >= 5:
        return "休市（周末）"
    current = moment.time()
    if current < time(9, 30):
        return "盘前"
    if current < time(11, 30):
        return "盘中（上午）"
    if current < time(13, 0):
        return "午间休市"
    if current < time(15, 0):
        return "盘中（下午）"
    return "已收盘"


def range_start(range_key: str, today: date) -> date | None:
    """First date of a named chart range, with month-end clamping.

    Args:
        range_key: One of the keys in ``NAV_RANGE_MONTHS``.
        today: Reference date the range ends at.

    Returns:
        The window start, or None for the "all" range.

    Raises:
        KeyError: `range_key` is not a known range name.
    """
    months = NAV_RANGE_MONTHS[range_key]
    if months is None:
        return None
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
