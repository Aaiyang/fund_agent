"""When a 定投 plan is due to debit.

The platform decides this, not us — but the plan is something the user states
(每几周/每月几号、多少钱), so the app can work out which installments it has
already been told to record and write them as ordinary purchases. Days that
fall on a non-trading day roll the same way an order does, in
:mod:`app.analytics.settlement`.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

Frequency = Literal["daily", "weekly", "biweekly", "monthly"]

_STEP_DAYS: dict[str, int] = {"daily": 1, "weekly": 7, "biweekly": 14}


def _month_start(moment: date) -> date:
    """The first day of the month after ``moment``."""
    return date(moment.year + (moment.month == 12), moment.month % 12 + 1, 1)


def _day_in_month(run_day: int, moment: date) -> int:
    """Clamp 每月 29-31 号 to the month's last day, the way the platforms do."""
    return min(run_day, calendar.monthrange(moment.year, moment.month)[1])


def first_due(frequency: Frequency, run_day: int, start: date) -> date:
    """The first scheduled day on or after the plan starts."""
    if frequency == "daily":
        return start
    if frequency == "monthly":
        candidate = start.replace(day=_day_in_month(run_day, start))
        return candidate if candidate >= start else _next_monthly(run_day, candidate)
    # run_day is an ISO weekday: 1 = Monday … 7 = Sunday.
    ahead = (run_day % 7 - start.isoweekday()) % 7
    return start + timedelta(days=ahead)


def _next_monthly(run_day: int, moment: date) -> date:
    following = _month_start(moment)
    return following.replace(day=_day_in_month(run_day, following))


def due_days(
    frequency: Frequency,
    run_day: int,
    start: date,
    end: date | None,
    after: date | None,
    through: date,
) -> list[date]:
    """Every scheduled day in ``(after, through]`` the plan still owes.

    A plan that was never settled starts from its own first due day; one being
    caught up months later jumps straight to what is outstanding instead of
    walking the history it already recorded.
    """
    day = first_due(frequency, run_day, start)
    if after is not None and day <= after:
        step = _STEP_DAYS.get(frequency)
        if step:
            day = day + timedelta(days=step * ((after - day).days // step + 1))
        else:
            while day <= after:
                day = _next_monthly(run_day, day)
    days: list[date] = []
    while day <= through and (end is None or day <= end):
        days.append(day)
        day = day + timedelta(days=step) if (step := _STEP_DAYS.get(frequency)) else _next_monthly(run_day, day)
    return days
