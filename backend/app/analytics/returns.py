"""Period return calculations over NAV series."""

from datetime import date, timedelta
from typing import NamedTuple


class NavPoint(NamedTuple):
    """A single (date, unit NAV) point, ascending by date."""

    date: date
    nav: float


# A disclosed 0.00% alongside a NAV that moved is the source's "no session today"
# marker — QDII funds get one for every overseas holiday — not a measured return.
# The tolerance keeps the genuine flat days, where the NAV only moved far enough to
# round to 0.00%.
_UNDISCLOSED_CHANGE_PP = 0.05


def disclosed_change(previous_nav: float | None, nav: float | None, disclosed: float | None) -> float | None:
    """The fund's published daily change, or None when it never said anything.

    Only a reported zero is ever second-guessed: a non-zero figure is the fund
    company's own number (and the one that accounts for distributions, which a raw
    NAV step does not), while a zero contradicted by the NAV series is a gap.
    """
    if disclosed is None:
        return None
    if disclosed != 0 or not previous_nav or previous_nav <= 0 or nav is None:
        return disclosed
    implied = abs(nav - previous_nav) / previous_nav * 100.0
    return None if implied >= _UNDISCLOSED_CHANGE_PP else disclosed


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
