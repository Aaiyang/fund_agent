"""净值序列上的最大回撤."""

from app.analytics.returns import NavPoint


def max_drawdown(points: list[NavPoint]) -> float | None:
    """返回峰到谷的最大跌幅，用负数比例表示.

    点数不足两个、或所有净值都非正时返回 None。
    """
    if len(points) < 2:
        return None
    peak = 0.0
    worst = 0.0
    saw_valid = False
    for point in points:
        if point.nav <= 0:
            continue
        saw_valid = True
        peak = max(peak, point.nav)
        drawdown = point.nav / peak - 1
        worst = min(worst, drawdown)
    return worst if saw_valid else None
