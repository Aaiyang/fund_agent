"""Period return calculations over NAV series."""

from datetime import date, timedelta
from typing import NamedTuple


class NavPoint(NamedTuple):
    """A single (date, unit NAV) point, ascending by date."""

    date: date
    nav: float


def range_return(points: list[NavPoint], start: date, end: date) -> float | None:
    """Return the cumulative return between two dates.

    Uses the closest NAV on or before each boundary. None when fewer than
    two valid points exist.
    """
    if len(points) < 2:
        return None
    start_nav = _nav_on_or_before(points, start)
    end_nav = _nav_on_or_before(points, end)
    if start_nav is None or end_nav is None or start_nav <= 0:
        return None
    return (end_nav - start_nav) / start_nav


def period_return(points: list[NavPoint], end: date, months: int) -> float | None:
    """Return over the trailing `months` months ending at `end`."""
    start = end - timedelta(days=int(months * 30.44))
    return range_return(points, start, end)


def window_return(points: list[NavPoint], end: date, days: int) -> float | None:
    """Return over the trailing `days` calendar days ending at `end`."""
    return range_return(points, end - timedelta(days=days), end)


def _nav_on_or_before(points: list[NavPoint], target: date) -> float | None:
    """Find the NAV of the latest point dated on or before `target`."""
    result: float | None = None
    for point in points:
        if point.date > target:
            break
        result = point.nav
    return result
