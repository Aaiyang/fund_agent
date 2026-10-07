"""确定性的金融指标计算：全部由 Python 算出，绝不交给 LLM 做算术.

所有函数都要求传入按日期升序排列的净值序列（MVP spec 5.2 / 14.3）。
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
