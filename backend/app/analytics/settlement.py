"""Fund settlement rules: which trading day's NAV a purchase is priced against.

Pure calendar math on purpose. The app has no trading calendar, so weekends are
rolled over but statutory holidays are not; a purchase after the cutoff before a
long weekend is therefore off by the length of that break.
"""

from datetime import date, timedelta

# Orders placed before this hour price at the same day's NAV.
CUTOFF_HOUR = 15


def settlement_date(purchase_date: date, after_cutoff: bool) -> date:
    """Return the session whose NAV applies to a confirmed purchase."""
    day = purchase_date + timedelta(days=1) if after_cutoff else purchase_date
    return _next_session(day)


def holding_days(purchase_date: date, after_cutoff: bool, today: date) -> int:
    """Sessions held, counted from the settlement date and never negative."""
    return max((today - settlement_date(purchase_date, after_cutoff)).days, 0)


def _next_session(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day
