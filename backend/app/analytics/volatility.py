"""Annualized volatility from daily NAV returns."""

import math
from datetime import timedelta

from app.analytics.returns import NavPoint

_TRADING_DAYS_PER_YEAR = 252


def daily_returns(points: list[NavPoint]) -> list[float]:
    """Day-over-day simple returns, skipping zero/invalid NAVs."""
    returns: list[float] = []
    for previous, current in zip(points, points[1:], strict=False):
        if previous.nav > 0 and current.nav > 0 and current.date - previous.date <= timedelta(days=7):
            returns.append(current.nav / previous.nav - 1)
    return returns


def annualized_volatility(points: list[NavPoint]) -> float | None:
    """Annualized standard deviation of daily returns (sample, ddof=1).

    None when fewer than three valid points exist.
    """
    returns = daily_returns(points)
    if len(returns) < 3:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(_TRADING_DAYS_PER_YEAR)
