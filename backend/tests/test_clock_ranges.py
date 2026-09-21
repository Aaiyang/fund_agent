"""Calendar helpers: one clock for timestamps, one for business dates."""

from datetime import date

import pytest

from app.schemas.fund import NavRange
from app.utils.clock import NAV_RANGE_MONTHS, range_start


class TestNavRanges:
    def test_range_names_match_the_api_contract(self) -> None:
        """The Literal in the API schema and the math table must not drift."""
        assert set(NAV_RANGE_MONTHS) == set(NavRange.__args__)

    def test_all_reaches_back_to_inception(self) -> None:
        assert range_start("all", date(2026, 9, 21)) is None

    @pytest.mark.parametrize(
        ("range_key", "expected"),
        [
            ("1m", date(2026, 8, 21)),
            ("3m", date(2026, 6, 21)),
            ("6m", date(2026, 3, 21)),
            ("1y", date(2025, 9, 21)),
            ("3y", date(2023, 9, 21)),
        ],
    )
    def test_named_ranges(self, range_key: str, expected: date) -> None:
        assert range_start(range_key, date(2026, 9, 21)) == expected

    def test_rolls_back_into_the_previous_year(self) -> None:
        assert range_start("3m", date(2026, 2, 10)) == date(2025, 11, 10)

    def test_clamps_to_a_day_that_exists_in_the_target_month(self) -> None:
        # 31 Aug minus 6 months has no 31 February
        assert range_start("6m", date(2026, 8, 31)) == date(2026, 2, 28)

    def test_unknown_range_raises(self) -> None:
        with pytest.raises(KeyError):
            range_start("7d", date(2026, 9, 21))
