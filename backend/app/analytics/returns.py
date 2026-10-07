"""净值序列上的区间收益计算."""

from datetime import date, timedelta
from typing import NamedTuple


class NavPoint(NamedTuple):
    """单个（日期、单位净值）数据点，按日期升序排列."""

    date: date
    nav: float


# 披露涨跌幅为 0.00%、净值却又动了，说明这是数据源的「当日无交易」标记，
# 不是真正测出来的收益——QDII 基金每逢海外节假日都会给出一个。
# 留出这点容差是为了保住确实持平的交易日：那些天净值只动了
# 四舍五入之后仍然显示为 0.00% 的幅度。
_UNDISCLOSED_CHANGE_PP = 0.05


def disclosed_change(previous_nav: float | None, nav: float | None, disclosed: float | None) -> float | None:
    """返回基金自己公布的当日涨跌幅；它从未公布过时返回 None.

    只有「报出来是 0」这一种情况会被复核：非零值是基金公司自己的数
    （已经计入了分红，拿净值直接做差是算不出来的），而 0 与净值序列
    对不上时，只能当作数据缺口处理。
    """
    if disclosed is None:
        return None
    if disclosed != 0 or not previous_nav or previous_nav <= 0 or nav is None:
        return disclosed
    implied = abs(nav - previous_nav) / previous_nav * 100.0
    return None if implied >= _UNDISCLOSED_CHANGE_PP else disclosed


def range_return(points: list[NavPoint], start: date, end: date) -> float | None:
    """返回两个日期之间的累计收益率.

    窗口两端各取该日或之前最近一个交易日的净值；有效数据点不足
    两个时返回 None。
    """
    if len(points) < 2:
        return None
    start_nav = _nav_on_or_before(points, start)
    end_nav = _nav_on_or_before(points, end)
    if start_nav is None or end_nav is None or start_nav <= 0:
        return None
    return (end_nav - start_nav) / start_nav


def period_return(points: list[NavPoint], end: date, months: int) -> float | None:
    """以 `end` 为终点、向前回溯 `months` 个月的区间收益率."""
    start = end - timedelta(days=int(months * 30.44))
    return range_return(points, start, end)


def window_return(points: list[NavPoint], end: date, days: int) -> float | None:
    """以 `end` 为终点、向前回溯 `days` 个自然日的区间收益率."""
    return range_return(points, end - timedelta(days=days), end)


def _nav_on_or_before(points: list[NavPoint], target: date) -> float | None:
    """取日期不晚于 `target` 的最后一个点，返回它的单位净值."""
    result: float | None = None
    for point in points:
        if point.date > target:
            break
        result = point.nav
    return result
