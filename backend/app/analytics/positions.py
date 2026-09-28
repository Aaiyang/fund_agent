"""Money figures for one holding, derived from whatever the snapshot carries.

A third-party holdings screen rarely gives every column this app stores: it may
show only 当前持有金额, or the amount plus 持有收益. The app still owes the user a
cost basis, a P/L and a rate, so the missing ones are computed here rather than
shown as blanks or frozen into the row at write time.

The order matters and is the whole point of the module: a number the user
supplied always wins, then a number implied by two other supplied numbers, and
only then the single-lot estimate backed by the confirmation-date NAV.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionFigures:
    """Every money figure shown for a holding."""

    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    # True when 持仓成本 came from the confirmation-date NAV instead of a value
    # the user or the import supplied. The estimate assumes one lot, so the
    # entry form shows it as the thing to correct for repeat purchases.
    cost_derived: bool = False


def position_figures(
    *,
    market_value: float | None = None,
    shares: float | None = None,
    cost_amount: float | None = None,
    average_cost_nav: float | None = None,
    profit_loss: float | None = None,
    unit_nav: float | None = None,
    settled_nav: float | None = None,
) -> PositionFigures:
    """Resolve the figures a holdings row leaves open.

    Args:
        market_value: 持有金额 as stored.
        shares: 持有份额 as stored.
        cost_amount: 持仓成本 as stored.
        average_cost_nav: 平均成本净值 as stored.
        profit_loss: 持有收益 as stored.
        unit_nav: newest published unit NAV, the price 持有金额 is marked at.
        settled_nav: unit NAV of the session the purchase was priced against.

    Returns:
        PositionFigures: blanks stay ``None``; nothing is invented from a
        single figure, so a row carrying only 持有金额 has no cost at all.
    """
    resolved_shares = shares
    if resolved_shares is None and market_value is not None and unit_nav:
        resolved_shares = market_value / unit_nav

    cost = cost_amount
    if cost is None and market_value is not None and profit_loss is not None:
        cost = market_value - profit_loss
    if cost is None and market_value is not None and settled_nav is not None and unit_nav:
        # 份额 cancels out: amount over the newest NAV, back at the settled NAV.
        cost = market_value * settled_nav / unit_nav

    profit = profit_loss
    if profit is None and market_value is not None and cost is not None:
        profit = market_value - cost

    cost_nav = average_cost_nav
    if cost_nav is None and cost is not None and resolved_shares:
        cost_nav = cost / resolved_shares

    return PositionFigures(
        shares=resolved_shares,
        cost_amount=cost,
        average_cost_nav=cost_nav,
        profit_loss=profit,
        profit_loss_rate=profit / cost if profit is not None and cost else None,
        cost_derived=cost_amount is None and cost is not None,
    )
