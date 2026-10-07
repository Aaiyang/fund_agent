"""单只持仓的各项金额，以及这些金额的来源账本.

两条写入路径都在给同一条持仓供数，但它们不能去抢同一批字段：

* 加减仓写入 BUY/SELL 流水。流水才是账本，也是份额与持仓成本的唯一来源——
  ``project_ledger`` 逐行把它投影成份额与成本。
* 同步持仓搬回的是第三方页面上显示的数字。没有流水时它是唯一能用的来源；
  有流水时它只用来修正持有金额。

其余各项都是派生指标——收益率、成本净值、金额/成本/收益三元组里缺的那一个——
在查询时按上面两个来源现算，不落库。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# 一条流水只有两种资金流向。
Direction = Literal["BUY", "SELL"]

# 用户实际在记什么：定投的计价方式与买入完全一致，转换则同时是两条腿；
# 账本本身只关心加还是减，所以仓储层用 ``LEDGER_IN`` / ``LEDGER_OUT``
# 把这几个字面值映射成 Direction。
Operation = Literal["BUY", "SELL", "AUTO_INVEST", "CONVERT"]


@dataclass(frozen=True)
class PositionFigures:
    """持仓页面上展示的每一项金额."""

    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    # 这一行其实没有存哪几项。录入表单刻意不把派生值做成输入框：
    # 把算出来的数字当原文回填给用户，等他下次保存时，
    # 一次估算就变成了一条落库的事实。
    shares_derived: bool = False
    cost_derived: bool = False
    average_cost_nav_derived: bool = False
    profit_derived: bool = False


@dataclass(frozen=True)
class LedgerRow:
    """一条 BUY 或 SELL 流水，只留下投影需要用到的字段.

    ``amount`` 是当日实际发生的现金：买入是申购总金额，
    卖出是确认到账之后的赎回款。
    """

    kind: Direction
    shares: float
    amount: float


@dataclass(frozen=True)
class LedgerTotals:
    """某基金整条流水累计下来的份额与持仓成本."""

    shares: float
    cost_amount: float


@dataclass(frozen=True)
class OrderDelta:
    """一笔订单往账本里添了什么.

    ``amount`` 是账本应当记下的现金：买入记申购总金额，
    卖出记确认到账的赎回款。
    """

    shares: float
    amount: float
    fee: float


def price_buy(nav: float, amount: float, fee: float = 0.0) -> OrderDelta:
    """只有扣掉申购费之后剩下的钱才会换成份额.

    手续费仍然留在持仓成本里——这笔钱确实付出去了——但它买不到任何份额，
    所以持仓的成本净值会比成交当日略高一点。
    """
    return OrderDelta(shares=(amount - fee) / nav, amount=amount, fee=fee)


def price_sell(nav: float, shares: float, fee: float = 0.0) -> OrderDelta:
    """卖出按实际到手多少钱出账，即扣掉赎回费之后的金额."""
    return OrderDelta(shares=shares, amount=shares * nav - fee, fee=fee)


def project_ledger(rows: Sequence[LedgerRow]) -> LedgerTotals:
    """把某基金的 BUY/SELL 流水折叠成它们最终留下的持仓.

    卖出结转成本时按该笔持仓当时的均价扣减，而不是按卖出价。
    否则一次部分赎回会把已实现收益挪进剩余持仓的成本里，
    持有收益就会把这笔收益重复计算一遍。
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
    # 全部赎回后只剩分位级别的浮点噪声，不该记成负持仓。
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
    """补齐一条持仓记录里没有确定的各项金额.

    Args:
        market_value: 记录下来的持有金额。
        shares: 持有份额，取自记录本身或由流水投影得出。
        cost_amount: 持仓成本，取自记录本身或投影结果。
        average_cost_nav: 记录里的平均成本净值；一旦有流水就不再用它。
        profit_loss: 记录里的持有收益；只在没有流水时才有意义。
        unit_nav: 最新公布的单位净值，持有金额就是按它估的。

    Returns:
        PositionFigures: 缺的项保持 ``None``。不会凭孤立的一项编出其他项，
        所以只存了持有金额的那行根本没有任何成本可言。
    """
    resolved_shares = shares
    if resolved_shares is None and market_value is not None and unit_nav:
        resolved_shares = market_value / unit_nav

    cost = cost_amount
    if cost is None and average_cost_nav is not None and resolved_shares:
        # 持仓页面上显示的就是持仓成本价，所以它在这里是输入项：
        # 还留在基金里的钱，就是这个单价乘以持有的份额。
        cost = average_cost_nav * resolved_shares
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
        shares_derived=shares is None and resolved_shares is not None,
        cost_derived=cost_amount is None and cost is not None,
        average_cost_nav_derived=average_cost_nav is None and cost_nav is not None,
        profit_derived=profit_loss is None and profit is not None,
    )
