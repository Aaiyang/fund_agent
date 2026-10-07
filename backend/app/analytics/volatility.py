"""由日收益率算出的年化波动率."""

import math
from datetime import timedelta

from app.analytics.returns import NavPoint

_TRADING_DAYS_PER_YEAR = 252


def daily_returns(points: list[NavPoint]) -> list[float]:
    """逐日简单收益率，跳过净值为零或非法的数据点."""
    returns: list[float] = []
    for previous, current in zip(points, points[1:], strict=False):
        if previous.nav > 0 and current.nav > 0 and current.date - previous.date <= timedelta(days=7):
            returns.append(current.nav / previous.nav - 1)
    return returns


def annualized_volatility(points: list[NavPoint]) -> float | None:
    """日收益率的年化标准差（样本估计，ddof=1）.

    有效收益率不足三个时返回 None。
    """
    returns = daily_returns(points)
    if len(returns) < 3:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(_TRADING_DAYS_PER_YEAR)
