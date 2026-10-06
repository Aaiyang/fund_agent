"""估值的纯计算：结构化输入进，百分点或 None 出（不联网、不落库、不猜）.

三条口径写在这里，服务层与界面都不该再各自解释一遍：

1. **估不出来就返回 None**，不返回 0.0。0.0 是一个"今天没涨没跌"的事实断言，
   None 才是"我们没有依据"。界面对 None 显示 `--`。
2. **只估 A 股交易时段内的盘中涨跌**，判据是基金类型（QDII 的净值按境外日历公布，
   盘中给数等于预测今晚收盘）。基准里出现恒生/纳斯达克**不是**否决理由——A 股主动
   基金常带 10%~20% 的港股基准，那些只是让基准法取不到价，穿透照样能估。
3. **穿透的外推有下限**。前十大只占净值一小部分时，按覆盖度归一等于把噪声放大
   1/覆盖率 倍，那种数看着合理但没有依据，不如不给。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# 前十大穿透的最低覆盖度（占净值比例，百分点）。实测样本里主动型前十大普遍占
# 85%~95%，而指数联接基金只占 1.8%——后者正是这条门槛要挡掉的那一类。
MIN_PENETRATION_COVERAGE_PP = 50.0

EstimateMethod = Literal["index", "penetration", "unavailable"]


@dataclass(frozen=True)
class HoldingWeight:
    """一条披露持仓：股票代码与它占基金净值的比例（百分点）."""

    symbol: str
    weight_pp: float


def benchmark_change(
    parts: Sequence[tuple[str, float]],
    index_changes: Mapping[str, float],
) -> float | None:
    """按业绩比较基准加权出的当日涨跌（百分点）.

    `parts` 是 (指数名, 权重百分点)，`index_changes` 是这些指数当天的涨跌幅。
    任何一个指数取不到价就返回 None：基准是"整体"口径，缺一块就不是那条基准了，
    用剩下几块凑出来的数会系统性偏大或偏小。

    基准里的存款/现金段按 0 收益处理：它一天确实不产生百分比波动，这是通行近似，
    代价是估值会比实际略微偏大（现金段真有小利息时）。
    """
    if not parts:
        return None
    total = 0.0
    for name, weight in parts:
        change = index_changes.get(name)
        if change is None:
            return None
        total += weight * change / 100.0
    return total


def penetration_change(
    holdings: Sequence[HoldingWeight],
    stock_changes: Mapping[str, float],
    *,
    min_coverage_pp: float = MIN_PENETRATION_COVERAGE_PP,
) -> float | None:
    """前十大披露持仓的加权当日涨跌（百分点）.

    分母用的是**能取到行情的那部分权重之和**，等价于假设未披露的剩余持仓与已披露
    部分同涨同跌。不这么归一（直接 Σ权重×涨跌）会系统性低估，因为前十大通常只占
    净值的 60%~95%，剩下的仓位被当成了 0 收益。

    覆盖度低于门槛就不给值，理由见模块开头第 3 条。
    """
    usable = [(holding, stock_changes.get(holding.symbol)) for holding in holdings]
    usable = [(holding, change) for holding, change in usable if change is not None]
    if not usable:
        return None
    coverage = sum(holding.weight_pp for holding, _ in usable)
    if coverage < min_coverage_pp:
        return None
    return sum(holding.weight_pp * change for holding, change in usable) / coverage


def choose_method(
    *,
    qdii_fund: bool,
    benchmark_ready: bool,
    disclosed_coverage_pp: float,
    min_coverage_pp: float = MIN_PENETRATION_COVERAGE_PP,
) -> EstimateMethod:
    """选估值口径：能解释整体的先看基准，其次看披露持仓，都不行就不给.

    顺序是有意的：基准法实测误差在 0.07pp 量级，穿透法在 0.4~0.5pp 量级，前者
    可用时没有理由用后者。

    `qdii_fund` 必须由**基金类型**推出，不能由基准文本里出现"恒生"推出：A 股主动
    基金常带 10%~20% 的港股基准，它们照样可以穿透估，而 QDII 的净值按境外日历公
    布，盘中给数是在预测今晚的收盘，时间口径就不是同一个，精度再高也不能用。
    """
    if qdii_fund:
        return "unavailable"
    if benchmark_ready:
        return "index"
    if disclosed_coverage_pp >= min_coverage_pp:
        return "penetration"
    return "unavailable"
