"""估值接口的请求与响应.

`change_pct` 与基金表里的 `daily_return` 同口径（百分点，2.2 即 +2.2%），这样前端
两列能共用同一个格式化函数。`available=False` 时它是 None——不是 0.0，0.0 在界面
上读起来是"今天没涨没跌"，那是个事实断言。
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import BaseResponse

# 与 analytics.valuation.EstimateMethod 同一组取值。
EstimateMethod = Literal["index", "penetration", "unavailable"]

MAX_CODES = 50


class ValuationEstimateRequest(BaseModel):
    """POST /valuation/estimates 请求体."""

    codes: list[str] = Field(..., min_length=1, max_length=MAX_CODES, description="基金代码，一次最多 50 只")

    @field_validator("codes")
    @classmethod
    def normalize_codes(cls, value: list[str]) -> list[str]:
        """去重、补零到 6 位；形状不对直接 422，不静默丢掉一只."""
        cleaned: list[str] = []
        for code in value:
            digits = code.strip()
            if not digits.isdigit() or len(digits) not in (5, 6):
                raise ValueError("fund_code_must_be_5_or_6_digits")
            cleaned.append(digits.zfill(6))
        return sorted(set(cleaned))


class FundEstimateItem(BaseModel):
    """一只基金的盘中估值，以及"为什么是这个口径"或"为什么没有"."""

    fund_code: str
    available: bool = False
    method: EstimateMethod = "unavailable"
    change_pct: float | None = None
    # 人读的口径说明，例如「沪深300×95%」或「前十大 92.5%（2026年2季度）」。
    # 估值必须带着依据展示：同一个数字，跟基准还是跟持仓，可信度差一个量级。
    basis: str | None = None
    # 估值所依据行情的交易日：指数收盘日或持仓行情快照日。
    quote_date: date | None = None
    # 没有值时的原因码（fund_not_found / cross_timezone_calendar / no_quotable_basis /
    # thin_disclosure），界面按它决定是显示 `--` 还是显示一句解释。
    reason: str | None = None


class ValuationEstimatesResponse(BaseResponse):
    """POST /valuation/estimates 响应体."""

    items: list[FundEstimateItem] = []
    total: int = 0
    # 这批估值是什么时候算的：它是一次现算的快照，不是可以长期引用的数。
    generated_at: datetime
