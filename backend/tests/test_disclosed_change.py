"""A disclosed 0.00% that the NAV series contradicts is a gap, not a flat day."""

from app.analytics.returns import disclosed_change


def test_a_zero_contradicted_by_the_nav_series_reads_as_not_disclosed() -> None:
    """QDII funds get 0.00% on every overseas holiday while the NAV still moved.

    Rendering that as "today +0.00%" tells the holder the fund did not move, and
    turns 昨日收益 into a fabricated ¥0.00.
    """
    assert disclosed_change(previous_nav=3.3297, nav=3.3666, disclosed=0.0) is None


def test_a_genuinely_flat_day_keeps_its_zero() -> None:
    """The other kind of zero: the NAV really did not change, which is a fact."""
    assert disclosed_change(previous_nav=3.3666, nav=3.3666, disclosed=0.0) == 0.0


def test_a_step_that_only_rounds_to_zero_keeps_its_zero() -> None:
    """A one-ten-thousandth NAV step rounds to 0.00%, so the disclosure agrees."""
    assert disclosed_change(previous_nav=3.3666, nav=3.3667, disclosed=0.0) == 0.0


def test_a_non_zero_disclosure_is_never_second_guessed() -> None:
    """Only a reported zero is ever challenged.

    A non-zero figure is the fund company's own number and accounts for
    distributions, which a raw NAV step does not.
    """
    assert disclosed_change(previous_nav=3.0, nav=3.2, disclosed=-1.4) == -1.4


def test_the_first_point_of_a_series_has_nothing_to_contradict() -> None:
    assert disclosed_change(previous_nav=None, nav=3.3666, disclosed=0.0) == 0.0


def test_a_missing_disclosure_stays_missing() -> None:
    assert disclosed_change(previous_nav=3.3, nav=3.4, disclosed=None) is None


def test_the_tolerance_is_the_smallest_reportable_change() -> None:
    """A step big enough to report as 0.01% cannot honestly be read as 0.00%."""
    assert disclosed_change(previous_nav=100.0, nav=100.06, disclosed=0.0) is None
    assert disclosed_change(previous_nav=100.0, nav=100.03, disclosed=0.0) == 0.0
