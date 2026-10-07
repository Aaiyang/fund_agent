"""基金成交确认规则：一笔申购按哪个交易日的净值计价.

这里刻意只做纯日历运算。应用没有内置交易日历，所以只把周末往后顺延，
法定节假日不顺延；于是在长假前的截止点 15:00 之后下单时，
算出的确认日会比真实确认日整整晚上一个假期。
"""

from datetime import date, timedelta

# 在这个钟点之前提交的订单，按当日的净值成交。
CUTOFF_HOUR = 15


def settlement_date(purchase_date: date, after_cutoff: bool) -> date:
    """返回这笔已确认申购按哪一交易日的净值计价."""
    day = purchase_date + timedelta(days=1) if after_cutoff else purchase_date
    return _next_session(day)


def holding_days(purchase_date: date, after_cutoff: bool, today: date) -> int:
    """持有天数按交易日计：从确认日当天开始数，且永远不会是负数."""
    return max((today - settlement_date(purchase_date, after_cutoff)).days, 0)


def latest_session(day: date) -> date:
    """给定一个自然日，返回它当天或之前最近的一个交易日.

    没有自带日期的持仓从这里起算：钱早就在基金里了，所以应当从它在
    应用里被看到的那天数起，
    而不是从导入任务碰巧运行的那天数起。
    """
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _next_session(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day
