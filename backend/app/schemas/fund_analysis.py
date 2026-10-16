"""近一年基金分析的可核验指标与纯JSON图表协议."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class FundAnalysisRequest(BaseModel):
    """只接收公开基金代码，不让模型提供走势图数据."""

    model_config = ConfigDict(extra="forbid")
    fund_code: str = Field(pattern=r"^[0-9]{6}$", description="6位基金代码，保留前导零")


class FundChartReference(BaseModel):
    """Only select a public fund; clients fetch chart data through their existing API."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    type: Literal["fund_performance"] = "fund_performance"
    fund_code: str = Field(pattern=r"^[0-9]{6}$")


class FundChartPoint(BaseModel):
    """正的有限单位净值，不插值或用未知值补点."""

    model_config = ConfigDict(extra="forbid")
    date: date
    unit_nav: FiniteFloat = Field(gt=0)


class FundNavChart(BaseModel):
    """客户端后续可验证的固定折线协议，无URL或可执行表达式."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    type: Literal["line"] = "line"
    metric: Literal["unit_nav"] = "unit_nav"
    range_key: Literal["1y"] = "1y"
    sampling: Literal["weekly"] = "weekly"
    fund_code: str = Field(pattern=r"^[0-9]{6}$")
    title: str
    source: Literal["fund_service"] = "fund_service"
    requested_from: date
    requested_to: date
    observed_from: date
    observed_to: date
    as_of: date
    points: list[FundChartPoint] = Field(min_length=2, max_length=60)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_window(self) -> "FundNavChart":
        """严格升序、实际首尾与请求窗口一致；不接受隐藏范围扩张."""
        dates = [point.date for point in self.points]
        if any(current <= previous for previous, current in zip(dates, dates[1:], strict=False)):
            raise ValueError("chart dates must be strictly increasing")
        if not self.requested_from <= self.observed_from < self.observed_to <= self.requested_to:
            raise ValueError("chart outside requested window")
        if dates[0] != self.observed_from or dates[-1] != self.observed_to or self.as_of != self.observed_to:
            raise ValueError("chart endpoints do not match observed dates")
        return self


class FundNavMetrics(BaseModel):
    """均为比值0.1=10%，仅描述可用未复权单位净值样本，不是总回报.

    夏普/索提诺的无风险利率按 0 计（字段名以 ``_rf0`` 标明），因为系统里没有可信的
    无风险利率来源；样本不足 120 个有效日点或存在质量缺口时一律为 None。
    """

    metric_basis: Literal["unadjusted_unit_nav"] = "unadjusted_unit_nav"
    first_nav: FiniteFloat | None = None
    latest_nav: FiniteFloat | None = None
    min_nav: FiniteFloat | None = None
    max_nav: FiniteFloat | None = None
    observed_change_ratio: FiniteFloat | None = None
    nav_change_1m_ratio: FiniteFloat | None = None
    nav_change_3m_ratio: FiniteFloat | None = None
    nav_change_6m_ratio: FiniteFloat | None = None
    observed_max_drawdown_ratio: FiniteFloat | None = None
    drawdown_from_observed_peak_ratio: FiniteFloat | None = None
    range_position_ratio: FiniteFloat | None = Field(default=None, ge=0, le=1)
    annualized_nav_volatility_ratio: FiniteFloat | None = None
    max_drawdown_peak_date: date | None = None
    max_drawdown_trough_date: date | None = None
    sharpe_ratio_rf0: FiniteFloat | None = None
    sortino_ratio_rf0: FiniteFloat | None = None
    annualized_downside_deviation_ratio: FiniteFloat | None = None


class FundHoldingsCardItem(BaseModel):
    """One public, periodically disclosed stock weight (percentage points)."""

    model_config = ConfigDict(extra="forbid")
    stock_code: str = Field(min_length=1, max_length=32)
    stock_name: str = Field(min_length=1, max_length=100)
    weight: FiniteFloat = Field(ge=0, le=100)


class FundHoldingsCard(BaseModel):
    """Fixed disclosure-card protocol; excludes personal costs and positions."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    type: Literal["holdings"] = "holdings"
    fund_code: str = Field(pattern=r"^[0-9]{6}$")
    source: Literal["fund_service"] = "fund_service"
    report_date: str = Field(min_length=1, max_length=80)
    items: list[FundHoldingsCardItem] = Field(min_length=1, max_length=10)
    warnings: list[str] = Field(default_factory=list)


class FundAnalysisData(BaseModel):
    """分析数据不足也明确返回范围，而非虚构一年历史."""

    fund_code: str
    requested_from: date
    requested_to: date
    observed_from: date | None = None
    observed_to: date | None = None
    raw_count: int
    valid_daily_count: int
    invalid_count: int
    duplicate_count: int
    conflict_count: int
    max_gap_days: int | None = None
    window_start_covered: bool
    source_truncated: bool
    partial: bool
    stale: bool
    metrics: FundNavMetrics
    chart: FundNavChart | None = None
    warnings: list[str] = Field(default_factory=list)
