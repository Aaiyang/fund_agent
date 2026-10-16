"""风险与相对基准指标：口径可复核，样本不足就不给数，绝不外推."""

import math
import random
import statistics
from datetime import date, timedelta

import pytest

from app.analytics.returns import NavPoint
from app.analytics.risk_metrics import (
    align_series,
    alpha,
    annual_returns,
    beta,
    downside_deviation,
    drawdown_window,
    excess_return,
    sharpe,
    sortino,
    top10_concentration,
    tracking_error,
)

START = date(2023, 1, 2)


def _series(navs: list[float], start: date = START) -> list[NavPoint]:
    """按自然日构造一条升序净值序列."""
    return [NavPoint(date=start + timedelta(days=index), nav=nav) for index, nav in enumerate(navs)]


def _walk(length: int, seed: int, drift: float = 0.0004, step: float = 0.01) -> list[float]:
    """确定性的伪随机净值游走，长度是点数（收益数 = 长度 - 1）."""
    randoms = random.Random(seed)
    navs = [1.0]
    for _ in range(length - 1):
        navs.append(navs[-1] * (1 + drift + randoms.uniform(-step, step)))
    return navs


def _returns(navs: list[float]) -> list[float]:
    return [current / previous - 1 for previous, current in zip(navs, navs[1:], strict=False)]


def _leveraged(benchmark: list[NavPoint], multiple: float) -> list[NavPoint]:
    """构造日收益恒为基准 multiple 倍的基金序列."""
    navs = [benchmark[0].nav]
    for previous, current in zip(benchmark, benchmark[1:], strict=False):
        navs.append(navs[-1] * (1 + multiple * (current.nav / previous.nav - 1)))
    return [NavPoint(point.date, nav) for point, nav in zip(benchmark, navs, strict=True)]


class TestAlignSeries:
    def test_keeps_only_common_dates_without_interpolating(self) -> None:
        fund = _series([1.0, 1.1, 1.2, 1.3])
        benchmark = _series([10.0, 10.2, 10.4], start=START + timedelta(days=1))
        aligned = align_series(fund, benchmark)
        assert [point.date for point in aligned.fund] == [point.date for point in aligned.benchmark]
        assert [point.date.day for point in aligned.fund] == [3, 4, 5]

    def test_empty_when_fewer_than_two_common_dates(self) -> None:
        aligned = align_series(_series([1.0, 1.1]), _series([10.0, 10.1], start=START + timedelta(days=5)))
        assert aligned.fund == [] and aligned.benchmark == []

    def test_drops_non_positive_navs_on_either_side(self) -> None:
        fund = _series([1.0, 0.0, 1.2])
        benchmark = _series([10.0, 10.1, -1.0])
        assert align_series(fund, benchmark).fund == []


class TestSingleSeriesMetrics:
    def test_sharpe_matches_the_textbook_formula(self) -> None:
        navs = _walk(160, seed=7)
        returns = _returns(navs)
        expected = statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(252)
        assert sharpe(_series(navs)) == pytest.approx(expected, rel=1e-9)

    def test_sharpe_is_none_below_the_minimum_sample(self) -> None:
        assert sharpe(_series(_walk(120, seed=1))) is None

    def test_higher_risk_free_rate_lowers_sharpe(self) -> None:
        points = _series(_walk(160, seed=7))
        with_risk_free = sharpe(points, risk_free_ratio=0.05)
        without = sharpe(points)
        assert with_risk_free is not None and without is not None
        assert with_risk_free < without

    def test_downside_deviation_counts_only_the_below_target_days(self) -> None:
        # 120 个 +2% / -1% 交替的日收益：上行那半对下行波动没有贡献。
        navs = [1.0]
        for index in range(120):
            navs.append(navs[-1] * (1.02 if index % 2 == 0 else 0.99))
        expected = math.sqrt(0.01**2 / 2) * math.sqrt(252)
        assert downside_deviation(_series(navs)) == pytest.approx(expected, rel=1e-9)

    def test_sortino_is_none_when_there_is_no_downside(self) -> None:
        # 单调上涨：没有任何低于目标的日收益，下行波动为零，不能用无穷大充当「极好」。
        assert sortino(_series([1.0 + index * 0.01 for index in range(160)])) is None

    def test_sortino_is_finite_for_a_noisy_series(self) -> None:
        value = sortino(_series(_walk(160, seed=11)))
        assert value is not None and math.isfinite(value)


class TestBenchmarkRelativeMetrics:
    def test_beta_is_one_and_alpha_zero_for_an_identical_series(self) -> None:
        benchmark = _series(_walk(160, seed=3))
        aligned = align_series(benchmark, benchmark)
        assert beta(aligned) == pytest.approx(1.0)
        assert alpha(aligned) == pytest.approx(0.0, abs=1e-12)

    def test_beta_recovers_the_leverage_multiple(self) -> None:
        benchmark = _series(_walk(200, seed=5))
        aligned = align_series(_leveraged(benchmark, 2.0), benchmark)
        assert beta(aligned) == pytest.approx(2.0, rel=1e-9)

    def test_beta_is_none_when_the_benchmark_never_moves(self) -> None:
        benchmark = _series([10.0] * 160)
        assert beta(align_series(_series(_walk(160, seed=3)), benchmark)) is None

    def test_tracking_error_is_none_for_a_perfect_track(self) -> None:
        benchmark = _series(_walk(160, seed=3))
        assert tracking_error(align_series(benchmark, benchmark)) is None

    def test_tracking_error_grows_with_leverage(self) -> None:
        benchmark = _series(_walk(200, seed=5))
        error = tracking_error(align_series(_leveraged(benchmark, 2.0), benchmark))
        assert error is not None and error > 0

    def test_excess_return_is_the_arithmetic_difference(self) -> None:
        fund = _series([1.0, 1.1, 1.21])
        benchmark = _series([1.0, 1.05, 1.1025])
        assert excess_return(align_series(fund, benchmark)) == pytest.approx(0.21 - 0.1025)

    def test_relative_metrics_are_none_below_the_minimum_sample(self) -> None:
        benchmark = _series(_walk(50, seed=3))
        aligned = align_series(_series(_walk(50, seed=4)), benchmark)
        assert beta(aligned) is None and alpha(aligned) is None and tracking_error(aligned) is None


class TestDrawdownWindow:
    def test_reports_peak_and_trough_dates(self) -> None:
        points = _series([1.0, 1.2, 0.9, 1.0, 1.1])
        window = drawdown_window(points)
        assert window is not None
        assert window.peak_date == points[1].date
        assert window.trough_date == points[2].date
        assert window.ratio == pytest.approx(0.9 / 1.2 - 1)

    def test_none_for_a_monotonically_rising_series(self) -> None:
        assert drawdown_window(_series([1.0, 1.1, 1.2])) is None

    def test_keeps_the_earlier_peak_when_two_drawdowns_are_equal(self) -> None:
        points = _series([1.0, 1.2, 1.0, 1.2, 1.0])
        window = drawdown_window(points)
        assert window is not None and window.peak_date == points[1].date


class TestAnnualReturns:
    def test_splits_by_calendar_year_and_flags_partial_years(self) -> None:
        full = _series([1.0] + [1.0] * 363 + [1.1], start=date(2023, 1, 1))
        later = _series([2.0, 2.2], start=date(2024, 6, 1))
        rows = annual_returns(full + later)
        assert [row.year for row in rows] == [2023, 2024]
        assert rows[0].full_year is True
        assert rows[1].full_year is False
        assert rows[0].ratio == pytest.approx(0.1)

    def test_skips_years_with_fewer_than_two_points(self) -> None:
        assert annual_returns(_series([1.0, 1.1], start=date(2023, 12, 31))) == []


class TestTop10Concentration:
    def test_sums_percentage_points(self) -> None:
        assert top10_concentration([9.5, 8.0, 7.5]) == pytest.approx(25.0)

    def test_none_for_empty_or_out_of_range_weights(self) -> None:
        assert top10_concentration([]) is None
        assert top10_concentration([10.0, 101.0]) is None
        assert top10_concentration([-1.0]) is None
