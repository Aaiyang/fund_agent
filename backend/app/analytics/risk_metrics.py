"""风险与相对基准指标：全部在日点上计算，样本不足一律返回 None."""

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import NamedTuple

from app.analytics.returns import NavPoint
from app.analytics.volatility import daily_returns
from app.utils.market_quote_policy import finite_number

_TRADING_DAYS_PER_YEAR = 252
# 与既有年化波动率门槛一致：不足半年日点算出的年化风险指标没有意义，宁可不给。
_MIN_DAILY_OBSERVATIONS = 120
# daily_returns 用它剔除长假造成的伪跳空，配对收益沿用同一口径。
_MAX_GAP_DAYS = 7


class AlignedSeries(NamedTuple):
    """基金与基准在共同交易日上的两条序列，日期一一对应且等长."""

    fund: list[NavPoint]
    benchmark: list[NavPoint]


class AnnualReturn(NamedTuple):
    """单个自然年度的收益；首尾年份通常不满一年，由 full_year 标出."""

    year: int
    ratio: float
    first_date: date
    last_date: date
    full_year: bool


class DrawdownWindow(NamedTuple):
    """最大回撤的峰、谷日期与幅度（负比例）."""

    peak_date: date
    trough_date: date
    ratio: float


def align_series(fund: list[NavPoint], benchmark: list[NavPoint]) -> AlignedSeries:
    """取共同交易日交集；不插值、不前向填充，缺口就是缺口."""
    bench = {point.date: point.nav for point in benchmark if point.nav > 0}
    pairs = [(point, bench[point.date]) for point in fund if point.nav > 0 and point.date in bench]
    if len(pairs) < 2:
        return AlignedSeries(fund=[], benchmark=[])
    return AlignedSeries(
        fund=[point for point, _ in pairs],
        benchmark=[NavPoint(point.date, nav) for point, nav in pairs],
    )


def sharpe(points: list[NavPoint], risk_free_ratio: float = 0.0) -> float | None:
    """年化夏普比率.

    ``risk_free_ratio`` 是年化无风险利率（0.03 表示 3%）。默认 0 是一个必须写进结论的
    口径约定，不是测出来的数：系统里没有可信的无风险利率来源。
    """
    returns = daily_returns(points)
    if len(returns) < _MIN_DAILY_OBSERVATIONS:
        return None
    excess = [value - risk_free_ratio / _TRADING_DAYS_PER_YEAR for value in returns]
    deviation = _std(excess)
    if not deviation:
        return None
    return finite_number(_mean(excess) / deviation * math.sqrt(_TRADING_DAYS_PER_YEAR))


def downside_deviation(points: list[NavPoint], target_ratio: float = 0.0) -> float | None:
    """年化下行波动：只统计低于目标日收益的部分，分母用全部观测数."""
    returns = daily_returns(points)
    if len(returns) < _MIN_DAILY_OBSERVATIONS:
        return None
    target = target_ratio / _TRADING_DAYS_PER_YEAR
    squared = [min(value - target, 0.0) ** 2 for value in returns]
    return finite_number(math.sqrt(_mean(squared)) * math.sqrt(_TRADING_DAYS_PER_YEAR))


def sortino(points: list[NavPoint], risk_free_ratio: float = 0.0) -> float | None:
    """年化索提诺比率；下行波动为零时返回 None，不用无穷大充当「极好」."""
    returns = daily_returns(points)
    if len(returns) < _MIN_DAILY_OBSERVATIONS:
        return None
    downside = downside_deviation(points, risk_free_ratio)
    if not downside:
        return None
    excess = _mean(returns) - risk_free_ratio / _TRADING_DAYS_PER_YEAR
    return finite_number(excess * _TRADING_DAYS_PER_YEAR / downside)


def beta(series: AlignedSeries) -> float | None:
    """相对基准的日收益 beta；基准方差为零（例如参照货币指数）时返回 None."""
    return _beta_from_pairs(_paired_returns(series))


def alpha(series: AlignedSeries, risk_free_ratio: float = 0.0) -> float | None:
    """年化詹森 alpha：基金超出「无风险 + beta × 基准超额」的那部分."""
    pairs = _paired_returns(series)
    coefficient = _beta_from_pairs(pairs)
    if coefficient is None:
        return None
    daily_rf = risk_free_ratio / _TRADING_DAYS_PER_YEAR
    mean_fund = _mean([fund for fund, _ in pairs])
    mean_benchmark = _mean([benchmark for _, benchmark in pairs])
    daily_alpha = (mean_fund - daily_rf) - coefficient * (mean_benchmark - daily_rf)
    return finite_number(daily_alpha * _TRADING_DAYS_PER_YEAR)


def tracking_error(series: AlignedSeries) -> float | None:
    """年化跟踪误差：日超额收益的年化标准差；恒为零时返回 None."""
    pairs = _paired_returns(series)
    if len(pairs) < _MIN_DAILY_OBSERVATIONS:
        return None
    deviation = _std([fund - benchmark for fund, benchmark in pairs])
    if not deviation:
        return None
    return finite_number(deviation * math.sqrt(_TRADING_DAYS_PER_YEAR))


def excess_return(series: AlignedSeries) -> float | None:
    """共同窗口上的累计收益差（基金 − 基准），是算术差不是几何超额."""
    if len(series.fund) < 2 or len(series.benchmark) < 2:
        return None
    fund_ratio = series.fund[-1].nav / series.fund[0].nav - 1
    benchmark_ratio = series.benchmark[-1].nav / series.benchmark[0].nav - 1
    return finite_number(fund_ratio - benchmark_ratio)


def drawdown_window(points: list[NavPoint]) -> DrawdownWindow | None:
    """最大回撤的峰谷日期与幅度；点数不足两个或净值全非正时返回 None."""
    peak: NavPoint | None = None
    worst: DrawdownWindow | None = None
    lowest = 0.0
    for point in points:
        if point.nav <= 0:
            continue
        if peak is None or point.nav > peak.nav:
            peak = point
        ratio = point.nav / peak.nav - 1
        if ratio < lowest:
            lowest = ratio
            worst = DrawdownWindow(peak_date=peak.date, trough_date=point.date, ratio=ratio)
    return worst


def annual_returns(points: list[NavPoint]) -> list[AnnualReturn]:
    """按自然年切分的收益；某年有效点不足两个就整年不给，不折算成年化."""
    buckets: dict[int, list[NavPoint]] = {}
    for point in points:
        if point.nav > 0:
            buckets.setdefault(point.date.year, []).append(point)
    result: list[AnnualReturn] = []
    for year in sorted(buckets):
        rows = buckets[year]
        if len(rows) < 2:
            continue
        first, last = rows[0], rows[-1]
        ratio = finite_number(last.nav / first.nav - 1)
        if ratio is None:
            continue
        result.append(
            AnnualReturn(
                year=year,
                ratio=ratio,
                first_date=first.date,
                last_date=last.date,
                full_year=first.date.month == 1 and last.date.month == 12,
            )
        )
    return result


def top10_concentration(weights: list[float]) -> float | None:
    """前十大重仓合计权重（百分点）；空列表或含越界权重时返回 None."""
    if not weights:
        return None
    for weight in weights:
        value = finite_number(weight)
        if value is None or value < 0 or value > 100:
            return None
    return finite_number(sum(weights))


def weighted_benchmark_series(
    parts: Sequence[tuple[str, float]],
    series: Mapping[str, list[NavPoint]],
    cash_weight: float = 0.0,
) -> list[NavPoint]:
    """按基准权重把各成分指数合成一条归一化净值序列.

    ``parts`` 是（指数名, 权重百分点），``series`` 按指数名给原始收盘序列，
    ``cash_weight`` 是现金/存款段的权重百分点，按 0 收益处理（净值恒定）。

    缺任一成分、或共同交易日不足两天，一律返回空列表：按剩下的几段加权会系统性
    偏掉，缺一块的就不再是那条基准了。
    """
    if not parts:
        return []
    available = {name: series.get(name) or [] for name, _ in parts}
    if any(not points for points in available.values()):
        return []
    common = sorted(set.intersection(*(set(point.date for point in points) for points in available.values())))
    if len(common) < 2:
        return []
    maps = {name: {point.date: point.nav for point in points} for name, points in available.items()}
    start = common[0]
    if any(maps[name][start] <= 0 for name in maps):
        return []
    result: list[NavPoint] = []
    for day in common:
        value = sum(weight / 100.0 * (maps[name][day] / maps[name][start]) for name, weight in parts)
        value += max(cash_weight, 0.0) / 100.0
        normalized = finite_number(value)
        if normalized is None or normalized <= 0:
            return []
        result.append(NavPoint(day, normalized))
    return result


def safe_metric(metric: Callable[[list[NavPoint]], float | None], points: list[NavPoint]) -> float | None:
    """把溢出/除零当作「算不出来」，不让一次异常打断整份指标."""
    try:
        return finite_number(metric(points))
    except (OverflowError, ZeroDivisionError):
        return None


def _paired_returns(series: AlignedSeries) -> list[tuple[float, float]]:
    """同日配对的（基金, 基准）日收益；任一侧非法或间隔过长则整对丢弃."""
    pairs: list[tuple[float, float]] = []
    for index in range(1, len(series.fund)):
        previous_fund, current_fund = series.fund[index - 1], series.fund[index]
        previous_benchmark, current_benchmark = series.benchmark[index - 1], series.benchmark[index]
        if min(previous_fund.nav, current_fund.nav, previous_benchmark.nav, current_benchmark.nav) <= 0:
            continue
        if (current_fund.date - previous_fund.date).days > _MAX_GAP_DAYS:
            continue
        pairs.append((current_fund.nav / previous_fund.nav - 1, current_benchmark.nav / previous_benchmark.nav - 1))
    return pairs


def _beta_from_pairs(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < _MIN_DAILY_OBSERVATIONS:
        return None
    fund = [item for item, _ in pairs]
    benchmark = [item for _, item in pairs]
    mean_fund, mean_benchmark = _mean(fund), _mean(benchmark)
    variance = sum((value - mean_benchmark) ** 2 for value in benchmark) / (len(benchmark) - 1)
    if not variance:
        return None
    covariance = sum((f - mean_fund) * (b - mean_benchmark) for f, b in zip(fund, benchmark, strict=True)) / (
        len(benchmark) - 1
    )
    return finite_number(covariance / variance)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float | None:
    """样本标准差（ddof=1），与 analytics/volatility.py 保持同一口径."""
    if len(values) < 2:
        return None
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))
