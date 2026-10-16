"""对齐真实净值日期；不插值，不以周采样计算年化风险."""

from datetime import date

from app.analytics.drawdown import max_drawdown
from app.analytics.returns import NavPoint
from app.analytics.risk_metrics import drawdown_window, safe_metric, sharpe, sortino
from app.analytics.volatility import annualized_volatility
from app.schemas.fund_comparison import FundComparisonRow
from app.utils.market_quote_policy import finite_number


def aligned_nav_metrics(
    series: dict[str, list[NavPoint]], quality: dict[str, bool]
) -> tuple[list[date], dict[str, FundComparisonRow]]:
    """所有对象均参与交集，失败对象不被偷偷剔除；风险要求完整同日样本."""
    maps = {code: {point.date: point.nav for point in points} for code, points in series.items()}
    common = sorted(set.intersection(*(set(values) for values in maps.values()))) if maps else []
    rows = {code: FundComparisonRow(fund_code=code) for code in series}
    if len(common) < 2:
        return common, rows
    start, end = common[0], common[-1]
    common_set = set(common)
    for code, values in maps.items():
        row = rows[code]
        row.aligned_count = len(common)
        row.window_change_ratio = finite_number(values[end] / values[start] - 1)
        if row.window_change_ratio is None:
            row.gaps.append("净值变化超出有效数值范围，未提供变化率")
        available = {day for day in values if start <= day <= end}
        points = [NavPoint(day, values[day]) for day in common]
        max_gap = max((right - left).days for left, right in zip(common, common[1:], strict=False))
        dense = len(common) >= max(2, (end - start).days * 0.45)
        if not quality.get(code, False) or available != common_set or max_gap > 14 or not dense:
            row.gaps.append("日点质量或共同日期覆盖不足，不提供回撤和年化波动率比较")
            continue
        row.observed_max_drawdown_ratio = finite_number(max_drawdown(points))
        window = drawdown_window(points)
        row.max_drawdown_peak_date = window.peak_date if window else None
        row.max_drawdown_trough_date = window.trough_date if window else None
        if len(points) >= 120:
            row.annualized_nav_volatility_ratio = safe_metric(annualized_volatility, points)
            row.sharpe_ratio_rf0 = safe_metric(sharpe, points)
            row.sortino_ratio_rf0 = safe_metric(sortino, points)
        if row.annualized_nav_volatility_ratio is None:
            row.gaps.append("有效共同日点不足120或计算不可用，未提供年化波动率与夏普/索提诺")
    return common, rows
