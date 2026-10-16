"""分析指标在日点计算，显示按周采样；不把净值变化称为总回报."""

from app.analytics.drawdown import max_drawdown
from app.analytics.returns import NavPoint, range_return
from app.analytics.risk_metrics import downside_deviation, drawdown_window, safe_metric, sharpe, sortino
from app.analytics.volatility import annualized_volatility
from app.schemas.fund_analysis import FundChartPoint, FundNavMetrics
from app.utils.clock import range_start
from app.utils.market_quote_policy import finite_number


def weekly_chart_points(points: list[NavPoint]) -> list[FundChartPoint]:
    """保留实际首尾和每周最后可用净值，指标不能在此序列上计算."""
    if not points:
        return []
    weeks: dict[tuple[int, int], NavPoint] = {}
    for point in points:
        year, week, _ = point.date.isocalendar()
        weeks[(year, week)] = point
    selected = {point.date: point for point in weeks.values()}
    selected[points[0].date] = points[0]
    selected[points[-1].date] = points[-1]
    return [FundChartPoint(date=day, unit_nav=selected[day].nav) for day in sorted(selected)]


def nav_metrics(points: list[NavPoint], *, daily_quality: bool) -> FundNavMetrics:
    """未知保留None；区间位置是线性价格位置，不是估值分位或买卖信号."""
    if not points:
        return FundNavMetrics()
    first, latest = points[0].nav, points[-1].nav
    low, high = min(point.nav for point in points), max(point.nav for point in points)
    # 年化风险指标共用同一道门槛：质量有缺口或不足 120 个日点时一律不给，
    # 宁缺勿造，也不拿周采样去凑年化。
    risk_ready = daily_quality and len(points) >= 120
    volatility = safe_metric(annualized_volatility, points) if risk_ready else None
    sharpe_ratio = safe_metric(sharpe, points) if risk_ready else None
    sortino_ratio = safe_metric(sortino, points) if risk_ready else None
    downside = safe_metric(downside_deviation, points) if risk_ready else None
    window = drawdown_window(points)
    end = points[-1].date
    return FundNavMetrics(
        first_nav=first,
        latest_nav=latest,
        min_nav=low,
        max_nav=high,
        observed_change_ratio=finite_number(latest / first - 1) if len(points) >= 2 else None,
        nav_change_1m_ratio=finite_number(range_return(points, range_start("1m", end) or end, end)),
        nav_change_3m_ratio=finite_number(range_return(points, range_start("3m", end) or end, end)),
        nav_change_6m_ratio=finite_number(range_return(points, range_start("6m", end) or end, end)),
        observed_max_drawdown_ratio=finite_number(max_drawdown(points)),
        drawdown_from_observed_peak_ratio=finite_number(latest / high - 1) if len(points) >= 2 else None,
        range_position_ratio=(latest - low) / (high - low) if high > low else None,
        annualized_nav_volatility_ratio=volatility,
        max_drawdown_peak_date=window.peak_date if window else None,
        max_drawdown_trough_date=window.trough_date if window else None,
        sharpe_ratio_rf0=sharpe_ratio,
        sortino_ratio_rf0=sortino_ratio,
        annualized_downside_deviation_ratio=downside,
    )
