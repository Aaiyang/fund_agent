"""The backfill decision must not re-pull a series that already serves the range."""

from datetime import date, timedelta

from app.services.market_service import _covers, _window_change
from app.schemas.market import IndexPoint

TODAY = date(2026, 9, 22)


class TestCovers:
    def test_true_when_the_stored_span_reaches_the_window_start(self) -> None:
        assert _covers((date(2025, 1, 2), TODAY), TODAY - timedelta(days=91), TODAY) is True

    def test_false_when_the_earliest_row_is_inside_the_window(self) -> None:
        assert _covers((TODAY - timedelta(days=30), TODAY), TODAY - timedelta(days=91), TODAY) is False

    def test_false_when_the_newest_row_is_stale(self) -> None:
        assert _covers((date(2020, 1, 2), TODAY - timedelta(days=10)), None, TODAY) is False

    def test_open_range_only_needs_freshness(self) -> None:
        assert _covers((date(2020, 1, 2), TODAY - timedelta(days=2)), None, TODAY) is True


class TestWindowChange:
    def test_none_below_two_points(self) -> None:
        assert _window_change([IndexPoint(trade_date=TODAY, close=1.0)]) is None

    def test_close_to_close_change(self) -> None:
        points = [
            IndexPoint(trade_date=date(2026, 9, 1), close=100.0),
            IndexPoint(trade_date=date(2026, 9, 22), close=108.0),
        ]
        assert _window_change(points) == 0.08
