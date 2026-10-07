"""定投计划的扣款日落在哪一天.

真正决定扣款日的是销售平台，不是我们——但定投计划是用户自己说出来的
（每几周/每月几号、多少钱），所以应用能推算出哪些期已经交代过要记账，
并把它们写成一笔笔普通买入。落在非交易日的扣款日与下单一样顺延，
顺延规则见
:mod:`app.analytics.settlement`。
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

Frequency = Literal["daily", "weekly", "biweekly", "monthly"]

_STEP_DAYS: dict[str, int] = {"daily": 1, "weekly": 7, "biweekly": 14}


def _month_start(moment: date) -> date:
    """``moment`` 之后那个月的第一天."""
    return date(moment.year + (moment.month == 12), moment.month % 12 + 1, 1)


def _day_in_month(run_day: int, moment: date) -> int:
    """把每月 29-31 号压到当月最后一天，与各平台的扣款日做法一致."""
    return min(run_day, calendar.monthrange(moment.year, moment.month)[1])


def first_due(frequency: Frequency, run_day: int, start: date) -> date:
    """计划起始日当天或之后的第一个扣款日."""
    if frequency == "daily":
        return start
    if frequency == "monthly":
        candidate = start.replace(day=_day_in_month(run_day, start))
        return candidate if candidate >= start else _next_monthly(run_day, candidate)
    # run_day 是 ISO 星期序号：1 = 周一 … 7 = 周日。
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
    """取出 ``(after, through]`` 内这个计划还欠着的每一个扣款日.

    从未结算过的计划从自己的第一个扣款日排起；隔了几个月才补记时，
    直接跳到还欠着的那几期即可，不必再把它
    已经记过账的历史从头走一遍。
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
