"""Deterministic financial analytics computed in Python, never by an LLM.

All functions take NAV series sorted ascending by date (MVP spec 5.2 / 14.3).
"""

from app.analytics.drawdown import max_drawdown
from app.analytics.returns import disclosed_change, period_return, range_return, window_return
from app.analytics.volatility import annualized_volatility

__all__ = [
    "annualized_volatility",
    "disclosed_change",
    "max_drawdown",
    "period_return",
    "range_return",
    "window_return",
]
