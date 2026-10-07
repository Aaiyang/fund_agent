"""定投计划落在哪几天扣款，包括短月和补扣这两类边界."""

from datetime import date

from app.analytics.schedule import due_days, first_due


class TestFirstDue:
    def test_weekly_waits_for_the_named_weekday(self) -> None:
        # 2026-09-23 是周三，run_day 1 指周一
        assert first_due("weekly", 1, date(2026, 9, 23)) == date(2026, 9, 28)

    def test_a_start_on_the_named_day_counts_itself(self) -> None:
        assert first_due("weekly", 3, date(2026, 9, 23)) == date(2026, 9, 23)

    def test_monthly_uses_the_named_day_after_the_start(self) -> None:
        assert first_due("monthly", 5, date(2026, 9, 23)) == date(2026, 10, 5)

    def test_a_short_month_debits_on_its_last_day(self) -> None:
        assert first_due("monthly", 31, date(2026, 1, 1)) == date(2026, 1, 31)
        assert first_due("monthly", 31, date(2026, 2, 1)) == date(2026, 2, 28)

    def test_a_leap_february_debits_on_the_29th(self) -> None:
        assert first_due("monthly", 31, date(2028, 2, 1)) == date(2028, 2, 29)


class TestDaily:
    def test_every_day_starts_on_the_plan_start(self) -> None:
        assert first_due("daily", 1, date(2026, 9, 23)) == date(2026, 9, 23)

    def test_every_day_walks_the_calendar(self) -> None:
        days = due_days("daily", 1, date(2026, 9, 28), None, None, date(2026, 10, 1))
        assert days == [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)]

    def test_a_daily_plan_caught_up_yesterday_owes_today(self) -> None:
        days = due_days("daily", 1, date(2026, 9, 1), None, date(2026, 9, 28), date(2026, 9, 30))
        assert days == [date(2026, 9, 29), date(2026, 9, 30)]


class TestDueDays:
    def test_weekly_lists_every_named_weekday_in_the_window(self) -> None:
        days = due_days("weekly", 1, date(2026, 9, 28), None, None, date(2026, 10, 31))
        assert days == [
            date(2026, 9, 28),
            date(2026, 10, 5),
            date(2026, 10, 12),
            date(2026, 10, 19),
            date(2026, 10, 26),
        ]

    def test_biweekly_skips_a_week(self) -> None:
        days = due_days("biweekly", 5, date(2026, 9, 25), None, None, date(2026, 11, 30))
        assert days == [
            date(2026, 9, 25),
            date(2026, 10, 9),
            date(2026, 10, 23),
            date(2026, 11, 6),
            date(2026, 11, 20),
        ]

    def test_monthly_walks_the_calendar_and_clamps_february(self) -> None:
        days = due_days("monthly", 31, date(2026, 1, 1), None, None, date(2026, 4, 30))
        assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]

    def test_catching_up_skips_the_days_already_settled(self) -> None:
        days = due_days(
            "monthly",
            10,
            date(2025, 1, 10),
            None,
            date(2026, 7, 10),
            date(2026, 9, 30),
        )
        assert days == [date(2026, 8, 10), date(2026, 9, 10)]

    def test_an_end_date_stops_the_schedule(self) -> None:
        days = due_days("weekly", 1, date(2026, 9, 28), date(2026, 10, 15), None, date(2026, 10, 31))
        assert days == [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]

    def test_nothing_is_due_before_the_plan_starts(self) -> None:
        assert due_days("monthly", 1, date(2026, 9, 1), None, None, date(2026, 8, 31)) == []

    def test_a_plan_settled_today_owes_nothing_more(self) -> None:
        assert due_days("weekly", 1, date(2026, 9, 28), None, date(2026, 10, 5), date(2026, 10, 5)) == []
