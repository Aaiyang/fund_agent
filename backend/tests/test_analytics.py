"""确定性的金融计算绝不能交给 LLM 去做（spec 5.2）."""

import math
import statistics
from datetime import date, timedelta

import pytest

from app.analytics import annualized_volatility, max_drawdown, period_return, range_return, window_return
from app.analytics.returns import NavPoint

START = date(2026, 1, 1)


def _series(navs: list[float], start: date = START) -> list[NavPoint]:
    """按天构造一条升序的净值序列."""
    return [NavPoint(date=start + timedelta(days=index), nav=nav) for index, nav in enumerate(navs)]


class TestRangeReturn:
    def test_uses_nearest_nav_on_or_before_each_boundary(self) -> None:
        points = _series([1.0, 1.1, 1.2])
        # 结束边界落在非交易日上：取日期不晚于边界的那条最近记录
        assert range_return(points, points[0].date, points[2].date + timedelta(days=3)) == pytest.approx(0.2)

    def test_none_when_series_is_too_short(self) -> None:
        assert range_return(_series([1.0]), START, START + timedelta(days=10)) is None

    def test_none_when_start_nav_is_not_positive(self) -> None:
        points = _series([0.0, 1.0])
        assert range_return(points, points[0].date, points[1].date) is None

    def test_none_when_no_point_precedes_the_window(self) -> None:
        points = _series([1.0, 1.2])
        assert range_return(points, points[0].date - timedelta(days=30), points[1].date) is None


class TestPeriodReturn:
    def test_month_is_treated_as_30_44_days(self) -> None:
        points = _series([1.0] + [1.0] * 30 + [1.5])
        end = points[-1].date
        # 从 `end` 往回推 30.44 天的窗口，起点落在第一个点之后 2 天
        assert period_return(points, end, 1) == pytest.approx(0.5)

    def test_window_length_uses_30_44_days_per_month(self) -> None:
        # 只有第一行是低净值：12 个月窗口（365 天）能回溯到它，11 个月窗口（334 天）回溯不到。
        points = _series([1.0] + [3.0] * 365)
        end = points[-1].date
        assert period_return(points, end, 12) == pytest.approx(2.0)
        assert period_return(points, end, 11) == pytest.approx(0.0)


class TestWindowReturn:
    def test_window_length_is_exactly_the_given_days(self) -> None:
        # 只有第 0 天是低净值：7 天窗口覆盖得到它，6 天窗口覆盖不到
        points = _series([1.0] + [3.0] * 7)
        end = points[-1].date
        assert window_return(points, end, 7) == pytest.approx(2.0)
        assert window_return(points, end, 6) == pytest.approx(0.0)

    def test_none_when_window_reaches_before_the_series(self) -> None:
        points = _series([1.0, 1.2])
        assert window_return(points, points[-1].date, 30) is None


class TestMaxDrawdown:
    def test_reports_peak_to_trough_as_negative(self) -> None:
        assert max_drawdown(_series([1.0, 1.1, 0.55, 0.66])) == pytest.approx(-0.5)

    def test_zero_when_series_only_rises(self) -> None:
        assert max_drawdown(_series([1.0, 1.1, 1.2])) == 0.0

    def test_ignores_non_positive_navs(self) -> None:
        assert max_drawdown(_series([1.0, 0.0, 0.5])) == pytest.approx(-0.5)

    def test_none_when_no_valid_nav(self) -> None:
        assert max_drawdown(_series([0.0, -1.0])) is None


class TestAnnualizedVolatility:
    def test_sample_stdev_annualized_by_sqrt_252(self) -> None:
        points = _series([1.0, 1.1, 0.55, 0.66])
        expected = statistics.stdev([0.1, -0.5, 0.2]) * math.sqrt(252)
        assert annualized_volatility(points) == pytest.approx(expected)

    def test_none_below_three_returns(self) -> None:
        assert annualized_volatility(_series([1.0, 1.1, 1.2])) is None

    def test_skips_gaps_longer_than_a_week(self) -> None:
        gapped = [NavPoint(date(2026, 1, 1), 1.0), NavPoint(date(2026, 1, 10), 2.0)]
        assert annualized_volatility(gapped) is None
