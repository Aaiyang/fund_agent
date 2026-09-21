"""Max drawdown over a NAV series."""

from app.analytics.returns import NavPoint


def max_drawdown(points: list[NavPoint]) -> float | None:
    """Return the maximum peak-to-trough decline as a negative fraction.

    None when fewer than two points exist or all NAVs are non-positive.
    """
    if len(points) < 2:
        return None
    peak = 0.0
    worst = 0.0
    saw_valid = False
    for point in points:
        if point.nav <= 0:
            continue
        saw_valid = True
        peak = max(peak, point.nav)
        drawdown = point.nav / peak - 1
        worst = min(worst, drawdown)
    return worst if saw_valid else None
