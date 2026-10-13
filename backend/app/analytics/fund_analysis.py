"""分析指标在日点计算，显示按周采样；不把净值变化称为总回报."""

from app.analytics.drawdown import max_drawdown
from app.analytics.returns import NavPoint, range_return
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
    volatility = None
    if daily_quality and len(points) >= 120:
        try:
            volatility = finite_number(annualized_volatility(points))
        except (OverflowError, ZeroDivisionError):
            volatility = None
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
    )
