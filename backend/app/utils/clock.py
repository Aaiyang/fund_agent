"""Clock helpers — the single place where this app decides what "now" means.

Every timestamp column in the schema is `timestamp without time zone`, so a
tz-aware value is rejected by asyncpg and a naive *local* value silently drifts
against the rest of the table. Writes therefore all use :func:`utc_now`.

Calendar dates (`trade_date`, NAV dates) are business days on the Chinese fund
market, so they use ``FUND_BUSINESS_TZ`` rather than whatever zone the host
happens to run in.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def utc_now() -> datetime:
    """Return a naive UTC timestamp, matching the schema's column types."""
    return datetime.now(UTC).replace(tzinfo=None)


def business_today() -> date:
    """Return today's date on the fund market calendar."""
    return datetime.now(ZoneInfo(settings.FUND_BUSINESS_TZ)).date()
