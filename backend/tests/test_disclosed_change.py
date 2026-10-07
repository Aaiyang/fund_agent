"""披露写着 0.00%、净值序列却证明当天动过：这是数据缺口，不能当成平盘日."""

from app.analytics.returns import disclosed_change


def test_a_zero_contradicted_by_the_nav_series_reads_as_not_disclosed() -> None:
    """QDII 基金逢境外节假日一律披露 0.00%，可净值其实还在动.

    照搬成「今日 +0.00%」会让持有人以为基金没动，昨日收益也跟着
    变成捏出来的 ¥0.00。
    """
    assert disclosed_change(previous_nav=3.3297, nav=3.3666, disclosed=0.0) is None


def test_a_genuinely_flat_day_keeps_its_zero() -> None:
    """另一种零：净值当天真的没变，这是事实，那个 0.00% 要留住."""
    assert disclosed_change(previous_nav=3.3666, nav=3.3666, disclosed=0.0) == 0.0


def test_a_step_that_only_rounds_to_zero_keeps_its_zero() -> None:
    """万分之一量级的净值涨幅四舍五入后正是 0.00%，披露与净值互相印证."""
    assert disclosed_change(previous_nav=3.3666, nav=3.3667, disclosed=0.0) == 0.0


def test_a_non_zero_disclosure_is_never_second_guessed() -> None:
    """只有「报出来是 0」这一种情况会被复核.

    非零值是基金公司自己的数，已经计入了分红等因素，拿净值直接做差
    推不出它，所以不去质疑。
    """
    assert disclosed_change(previous_nav=3.0, nav=3.2, disclosed=-1.4) == -1.4


def test_the_first_point_of_a_series_has_nothing_to_contradict() -> None:
    assert disclosed_change(previous_nav=None, nav=3.3666, disclosed=0.0) == 0.0


def test_a_missing_disclosure_stays_missing() -> None:
    assert disclosed_change(previous_nav=3.3, nav=3.4, disclosed=None) is None


def test_the_tolerance_is_the_smallest_reportable_change() -> None:
    """幅度已经够报成 0.01% 的净值变动，不可能诚实地被读成 0.00%."""
    assert disclosed_change(previous_nav=100.0, nav=100.06, disclosed=0.0) is None
    assert disclosed_change(previous_nav=100.0, nav=100.03, disclosed=0.0) == 0.0
