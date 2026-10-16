"""业绩比较基准的原文、构成与相对指标；基准读不懂就不给相对数."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from app.schemas.fund import NavRange


class BenchmarkPartItem(BaseModel):
    """基准里的一段：指数名、权重百分点，以及能否落到可查的指数代码."""

    model_config = ConfigDict(extra="forbid")
    index_name: str
    weight_pp: FiniteFloat = Field(ge=0, le=100)
    index_code: str | None = None


class BenchmarkAnnualRow(BaseModel):
    """单个自然年上基金与基准的收益对照；首尾年份通常不满一年."""

    model_config = ConfigDict(extra="forbid")
    year: int
    fund_ratio: FiniteFloat | None = None
    benchmark_ratio: FiniteFloat | None = None
    excess_ratio: FiniteFloat | None = None
    full_year: bool = False


class FundBenchmarkData(BaseModel):
    """基准原文与构成始终给出；相对指标只在成分指数全部可查、样本足够时才有."""

    model_config = ConfigDict(extra="forbid")
    fund_code: str = Field(pattern=r"^[0-9]{6}$")
    range_key: NavRange
    benchmark_text: str | None = None
    parseable: bool = False
    parts: list[BenchmarkPartItem] = Field(default_factory=list)
    cash_weight_pp: FiniteFloat = Field(default=0.0, ge=0, le=100)
    has_offshore_index: bool = False
    fx_adjusted: bool = False
    unavailable_reason: str | None = None
    observed_from: date | None = None
    observed_to: date | None = None
    aligned_days: int = 0
    fund_return_ratio: FiniteFloat | None = None
    benchmark_return_ratio: FiniteFloat | None = None
    excess_return_ratio: FiniteFloat | None = None
    beta: FiniteFloat | None = None
    alpha_ratio: FiniteFloat | None = None
    tracking_error_ratio: FiniteFloat | None = None
    annual: list[BenchmarkAnnualRow] = Field(default_factory=list)
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)


class FundBenchmarkRequest(BaseModel):
    """只接收公开基金代码与命名区间，不让模型传指数代码或序列."""

    model_config = ConfigDict(extra="forbid")
    fund_code: str = Field(pattern=r"^[0-9]{6}$", description="6位基金代码，保留前导零")
    range_key: NavRange = Field(default="3y", description="相对指标的观察区间")
