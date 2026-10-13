"""仅基金资产桶的确定性金额情景，不推算价格、未来收益或现金总资产."""

import math
import re

from app.utils.market_quote_policy import finite_number


def position_weight(value: float | None, total: float) -> float | None:
    """未知市值或无有效分母时不伪造零占比."""
    value = finite_number(value)
    if value is None or value < 0 or not math.isfinite(total) or total <= 0 or value > total:
        return None
    return value / total


def portfolio_scenario_inputs(
    summary: dict, positions: dict, target_code: str | None
) -> tuple[float | None, float | None]:
    """核验同范围全量市值；截断、缺失、非有限数或汇总不一致均拒绝计算."""
    rows = positions.get("positions")
    total = finite_number(summary.get("total_market_value"))
    if not isinstance(rows, list) or total is None or total < 0 or len(rows) != summary.get("fund_count"):
        return None, None
    if any(not isinstance(row, dict) or not re.fullmatch(r"\d{6}", str(row.get("fund_code", ""))) for row in rows):
        return None, None
    values = [finite_number(row.get("market_value")) for row in rows]
    if any(value is None or value < 0 for value in values):
        return None, None
    if not math.isclose(sum(value for value in values if value is not None), total, rel_tol=1e-6, abs_tol=0.02):
        return None, None
    target = sum(
        value for row, value in zip(rows, values, strict=True) if row["fund_code"] == target_code and value is not None
    )
    return total, target if target_code is not None else None


def allocation_scenario(
    *, total: float | None, target: float | None, amount: float | None, action: str | None
) -> dict:
    """新增资金进入或赎回离开基金资产桶的条件情景，金额缺失时不猜测."""
    values = (total, target, amount)
    if any(value is None or not math.isfinite(value) for value in values):
        return {"available": False, "reason": "缺少明确金额或完整同范围基金市值，未计算操作后比例"}
    assert total is not None and target is not None and amount is not None
    if total < 0 or target < 0 or target > total or amount <= 0:
        return {"available": False, "reason": "市值或拟操作金额无效"}
    if action in {"build", "increase"}:
        after_total, after_target = total + amount, target + amount
        assumption = "假设新增资金进入基金资产桶；未纳入现金、其他资产和交易费用"
    elif action in {"reduce", "exit"}:
        if amount > target:
            return {"available": False, "reason": "拟赎回金额超过已核验的该基金市值"}
        if action == "exit" and not math.isclose(amount, target, abs_tol=0.01):
            return {"available": False, "reason": "所给金额不是全部已核验市值，不能作为清仓情景"}
        after_total, after_target = total - amount, target - amount
        assumption = "假设赎回资金离开基金资产桶；未纳入到账时间、现金和交易费用"
    else:
        return {"available": False, "reason": "尚未明确具体操作，未计算金额情景"}
    return {
        "available": True,
        "assumption": assumption,
        "amount": amount,
        "before_fund_assets": total,
        "after_fund_assets": after_total,
        "before_target_value": target,
        "after_target_value": after_target,
        "before_weight_ratio": target / total if total > 0 else None,
        "after_weight_ratio": after_target / after_total if after_total > 0 else None,
    }
