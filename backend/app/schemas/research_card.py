"""研究卡片仅携带白名单标识和情景参数，不携带模型生成行情或URL."""

from typing import Annotated, Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class StockChartReference(BaseModel):
    """已确认股票的公开价格图引用."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    type: Literal["stock_price"] = "stock_price"
    symbol: str = Field(pattern=r"^(?:(?:sh|sz|bj)\d{6}|hk\d{5}|us[A-Z][A-Z.]{0,10})$")


class SectorChartReference(BaseModel):
    """真实目录中板块的行情引用."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    type: Literal["sector_quote"] = "sector_quote"
    sector_code: str = Field(pattern=r"^BK\d{4,6}$")
    sector_type: Literal["industry", "concept"]


class AllocationChartReference(BaseModel):
    """本人基金账本的只读条件试算引用."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    type: Literal["fund_allocation"] = "fund_allocation"
    fund_code: str = Field(pattern=r"^\d{6}$")
    account_id: int | None = Field(default=None, ge=1, strict=True)
    action: Literal["build", "increase", "reduce", "exit"]
    amount: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False, strict=True)


ResearchCard = Annotated[
    StockChartReference | SectorChartReference | AllocationChartReference, Field(discriminator="type")
]
RESEARCH_CARD_ADAPTER = TypeAdapter(ResearchCard)


class AllocationPreviewResponse(BaseModel):
    """当前账本的只读条件试算，没有交易写入."""

    reference: AllocationChartReference
    captured_at: datetime
    scenario: dict
    warnings: list[str] = Field(default_factory=list)


def card_code_block(card: StockChartReference | SectorChartReference | AllocationChartReference) -> str:
    """渲染固定JSON引用，不支持脚本或自定义接口地址."""
    return "```research-chart\n" + card.model_dump_json() + "\n```"
