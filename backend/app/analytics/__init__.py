"""确定性的金融指标计算：全部由 Python 算出，绝不交给 LLM 做算术.

所有函数都要求传入按日期升序排列的净值序列（MVP spec 5.2 / 14.3）。
"""

from app.analytics.drawdown import max_drawdown
from app.analytics.returns import disclosed_change, period_return, range_return, window_return
from app.analytics.risk_metrics import (
    AlignedSeries,
    AnnualReturn,
    DrawdownWindow,
    align_series,
    alpha,
    annual_returns,
    beta,
    downside_deviation,
    drawdown_window,
    excess_return,
    safe_metric,
    sharpe,
    sortino,
    top10_concentration,
    tracking_error,
    weighted_benchmark_series,
)
from app.analytics.volatility import annualized_volatility

__all__ = [
    "AlignedSeries",
    "AnnualReturn",
    "DrawdownWindow",
    "align_series",
    "alpha",
    "annual_returns",
    "annualized_volatility",
    "beta",
    "disclosed_change",
    "downside_deviation",
    "drawdown_window",
    "excess_return",
    "max_drawdown",
    "period_return",
    "range_return",
    "safe_metric",
    "sharpe",
    "sortino",
    "top10_concentration",
    "tracking_error",
    "weighted_benchmark_series",
    "window_return",
]
