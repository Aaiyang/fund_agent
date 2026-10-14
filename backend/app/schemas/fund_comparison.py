"""公开基金对比：输入仅含基金代码，输出统一窗口的代码计算结果."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

FundCode = Annotated[str, Field(pattern=r"^[0-9]{6}$")]


class FundComparisonRequest(BaseModel):
    """两到三只不同基金；保留前导零和不同份额代码."""

    model_config = ConfigDict(extra="forbid")
    fund_codes: list[FundCode] = Field(min_length=2, max_length=3)

    @field_validator("fund_codes")
    @classmethod
    def distinct_codes(cls, codes: list[str]) -> list[str]:
        """仅去除同代码重复，不合并不同份额代码."""
        unique = list(dict.fromkeys(codes))
        if len(unique) < 2:
            raise ValueError("基金对比至少需要两只不同代码的基金")
        return unique


class FundComparisonRow(BaseModel):
    """指标均在共同窗口计算；无可靠证据保留None."""

    fund_code: str
    observed_from: date | None = None
    observed_to: date | None = None
    valid_daily_count: int = 0
    aligned_count: int = 0
    window_change_ratio: FiniteFloat | None = None
    observed_max_drawdown_ratio: FiniteFloat | None = None
    annualized_nav_volatility_ratio: FiniteFloat | None = None
    stale: bool = False
    gaps: list[str] = Field(default_factory=list)
    chart_code_block: str | None = None


class FundComparisonData(BaseModel):
    """共同日期不保证相同资产类别、币种或含分红回报可比."""

    metric_basis: Literal["unadjusted_unit_nav"] = "unadjusted_unit_nav"
    status: Literal["completed", "partial", "unavailable"]
    requested_from: date
    requested_to: date
    common_from: date | None = None
    common_to: date | None = None
    common_count: int = 0
    stale: bool = False
    rows: list[FundComparisonRow]
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
