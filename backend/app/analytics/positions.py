"""Money figures for one holding, and the ledger they come from.

Two paths feed a position, and they must not fight over the same columns:

* 加减仓 writes BUY/SELL rows. Those are the ledger, and it is the only source
  for 份额 and 持仓成本 — ``project_ledger`` walks it into a projection.
* 同步持仓 reports what a third-party screen shows. Without a ledger it is the
  only source there is; with one it only corrects 持有金额.

Everything else — 收益率, 成本净值, the missing member of an amount/cost/profit
triple — is derived at query time from those two sources.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# The two directions a fund order can go. A holdings snapshot is not one of
# them: it reports a state, while these describe the events that add up to it.
Direction = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class PositionFigures:
    """Every money figure shown for a holding."""

    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    # True when 持仓成本 was implied by two other stored figures rather than
    # recorded. The entry form keeps those off its inputs: a derived number
    # must not come back looking like something the user asserted.
    cost_derived: bool = False


@dataclass(frozen=True)
class LedgerRow:
    """One BUY or SELL row, narrowed to what the projection consumes.

    ``amount`` is cash on the day: the subscription total for a buy, the
    settled proceeds for a sell.
    """

    kind: Direction
    shares: float
    amount: float


@dataclass(frozen=True)
class LedgerTotals:
    """份额 and 持仓成本 carried by a fund's whole ledger."""

    shares: float
    cost_amount: float


@dataclass(frozen=True)
class OrderDelta:
    """What one order contributes to the ledger.

    ``amount`` is the cash the ledger should carry: the subscription total for a
    buy, the settled proceeds for a sell.
    """

    shares: float
    amount: float
    fee: float


def price_buy(nav: float, amount: float, fee: float = 0.0) -> OrderDelta:
    """Only the money that clears the subscription fee becomes shares.

    The fee stays in 持仓成本 — it was paid — but it buys nothing, which is why
    a holding's 成本净值 comes out slightly above the NAV it settled at.
    """
    return OrderDelta(shares=(amount - fee) / nav, amount=amount, fee=fee)


def price_sell(nav: float, shares: float, fee: float = 0.0) -> OrderDelta:
    """A sell leaves with what it actually received, redemption fee excluded."""
    return OrderDelta(shares=shares, amount=shares * nav - fee, fee=fee)


def project_ledger(rows: Sequence[LedgerRow]) -> LedgerTotals:
    """Fold a fund's BUY/SELL rows into the holding they leave behind.

    A sell takes cost out at the average it was carried at, not at the sale
    price — otherwise a partial exit would move the realized gain into the
    remaining cost basis and 持有收益 would silently double-count it.
    """
    shares = 0.0
    cost = 0.0
    for row in rows:
        if row.kind == "BUY":
            shares += row.shares
            cost += row.amount
            continue
        if shares <= 0:
            continue
        sold = min(row.shares, shares)
        cost -= cost * sold / shares
        shares -= sold
    # A full exit leaves cent-sized float noise, not a negative holding.
    return LedgerTotals(shares=shares if shares > 0 else 0.0, cost_amount=cost if cost > 0 else 0.0)


def position_figures(
    *,
    market_value: float | None = None,
    shares: float | None = None,
    cost_amount: float | None = None,
    average_cost_nav: float | None = None,
    profit_loss: float | None = None,
    unit_nav: float | None = None,
) -> PositionFigures:
    """Resolve the figures a holdings row leaves open.

    Args:
        market_value: 持有金额 as recorded.
        shares: 持有份额 as recorded or projected from the ledger.
        cost_amount: 持仓成本 as recorded or projected.
        average_cost_nav: 平均成本净值 as recorded; ignored once a ledger exists.
        profit_loss: 持有收益 as recorded; only meaningful without a ledger.
        unit_nav: newest published unit NAV, the price 持有金额 is marked at.

    Returns:
        PositionFigures: blanks stay ``None``. Nothing is invented from a single
        figure, so a row carrying only 持有金额 has no cost at all.
    """
    resolved_shares = shares
    if resolved_shares is None and market_value is not None and unit_nav:
        resolved_shares = market_value / unit_nav

    cost = cost_amount
    if cost is None and market_value is not None and profit_loss is not None:
        cost = market_value - profit_loss

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
