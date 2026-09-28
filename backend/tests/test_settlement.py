"""Tests for the fund settlement calendar helper."""

from datetime import date

from app.analytics.settlement import holding_days, settlement_date

# 2026-09-21 Monday, 2026-09-25 Friday, 2026-09-26 Saturday.
MONDAY = date(2026, 9, 21)
FRIDAY = date(2026, 9, 25)
SATURDAY = date(2026, 9, 26)
WEDNESDAY = date(2026, 9, 23)


class TestSettlementDate:
    def test_before_cutoff_prices_on_the_same_day(self) -> None:
        assert settlement_date(WEDNESDAY, after_cutoff=False) == WEDNESDAY

    def test_after_cutoff_prices_on_the_next_session(self) -> None:
        assert settlement_date(WEDNESDAY, after_cutoff=True) == date(2026, 9, 24)

    def test_after_cutoff_on_friday_lands_on_monday(self) -> None:
        assert settlement_date(FRIDAY, after_cutoff=True) == date(2026, 9, 28)

    def test_a_weekend_date_rolls_to_monday_either_way(self) -> None:
        assert settlement_date(SATURDAY, after_cutoff=False) == date(2026, 9, 28)
        assert settlement_date(SATURDAY, after_cutoff=True) == date(2026, 9, 28)


class TestHoldingDays:
    def test_counts_from_the_settlement_date(self) -> None:
        assert holding_days(MONDAY, after_cutoff=False, today=WEDNESDAY) == 2
        assert holding_days(MONDAY, after_cutoff=True, today=WEDNESDAY) == 1

    def test_a_future_purchase_never_goes_negative(self) -> None:
        assert holding_days(FRIDAY, after_cutoff=True, today=MONDAY) == 0
