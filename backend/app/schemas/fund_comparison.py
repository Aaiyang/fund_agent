"""公开基金对比：输入仅含基金代码，输出统一窗口的代码计算结果."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

from app.utils.clock import business_today

FundCode = Annotated[str, Field(pattern=r"^[0-9]{6}$")]
MAX_CHART_WINDOW_DAYS = 370


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
    """指标均在共同窗口计算；无可靠证据保留None.

    夏普/索提诺的无风险利率按 0 计（字段名以 ``_rf0`` 标明）：系统里没有可信的
    无风险利率来源，这个口径必须跟着数字一起被读到。
    """

    fund_code: str
    observed_from: date | None = None
    observed_to: date | None = None
    valid_daily_count: int = 0
    aligned_count: int = 0
    window_change_ratio: FiniteFloat | None = None
    observed_max_drawdown_ratio: FiniteFloat | None = None
    max_drawdown_peak_date: date | None = None
    max_drawdown_trough_date: date | None = None
    annualized_nav_volatility_ratio: FiniteFloat | None = None
    sharpe_ratio_rf0: FiniteFloat | None = None
    sortino_ratio_rf0: FiniteFloat | None = None
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


class FundComparisonSeriesRequest(BaseModel):
    """按报告生成的固定共同窗口重取对齐序列；只给代码和日期，不接受任意范围."""

    model_config = ConfigDict(extra="forbid")
    fund_codes: list[FundCode] = Field(min_length=2, max_length=3)
    from_date: date
    to_date: date

    @field_validator("fund_codes")
    @classmethod
    def distinct_codes(cls, codes: list[str]) -> list[str]:
        """同代码去重，A/C 份额仍按不同对象保留."""
        unique = list(dict.fromkeys(codes))
        if len(unique) < 2:
            raise ValueError("基金对比至少需要两只不同代码的基金")
        return unique

    @model_validator(mode="after")
    def valid_window(self) -> "FundComparisonSeriesRequest":
        """窗口必须有正向跨度、不得超一年，也不能查未来日期."""
        if self.from_date >= self.to_date:
            raise ValueError("对比窗口起点必须早于终点")
        if (self.to_date - self.from_date).days > MAX_CHART_WINDOW_DAYS:
            raise ValueError("对比窗口不得超过一年")
        if self.to_date > business_today():
            raise ValueError("对比窗口不能包含未来日期")
        return self


class FundComparisonPoint(BaseModel):
    """归一后的同日累计变化；0.1 表示 10%，不是单位净值."""

    nav_date: date
    change_ratio: FiniteFloat


class FundComparisonPeriodReturns(BaseModel):
    """共同窗口内的阶段收益；没有覆盖该阶段的基金保留 None."""

    return_1m: FiniteFloat | None = None
    return_3m: FiniteFloat | None = None
    return_6m: FiniteFloat | None = None
    return_1y: FiniteFloat | None = None


class FundComparisonSeriesFund(BaseModel):
    """一只基金在共同日期上的归一序列；名称只用于图例."""

    fund_code: str
    fund_name: str | None = None
    points: list[FundComparisonPoint] = Field(default_factory=list)
    period_returns: FundComparisonPeriodReturns = Field(default_factory=FundComparisonPeriodReturns)


class FundComparisonSeriesResponse(BaseModel):
    """按固定共同窗口重取的对齐序列；指标仍以报告消息里的引用为准."""

    metric_basis: Literal["unadjusted_unit_nav"] = "unadjusted_unit_nav"
    common_from: date | None = None
    common_to: date | None = None
    aligned_count: int = 0
    funds: list[FundComparisonSeriesFund] = Field(default_factory=list)
    stale: bool = False
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
