"""持仓导入的契约：输入载荷、草稿条目、provider 协议."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ManualPositionInput(BaseModel):
    """一条手动录入的持仓."""

    fund_code: str | None = Field(default=None, max_length=12)
    fund_name: str | None = Field(default=None, max_length=200)
    market_value: float | None = Field(default=None, ge=0)
    shares: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    average_cost_nav: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    profit_loss_rate: float | None = None


class HoldingImportPayload(BaseModel):
    """provider 的输入：手动录入的持仓行，和/或截图的本地文件路径."""

    account_id: int
    manual_positions: list[ManualPositionInput] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)


class RawExtractedPosition(BaseModel):
    """从截图里抽出的一条持仓，还没做基金解析.

    每个字段都可能为空——各家 App 截图展示的字段差别很大（MVP spec 3.7.2）。
    confidence 是逐条打的（0.0–1.0）。
    """

    fund_name: str | None = None
    fund_code: str | None = None
    market_value: float | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    daily_profit_loss: float | None = None
    # 名称被 App 用省略号截断了：这种名称不可能精确匹配到某只基金，
    # 复核页要给出候选，而不是替用户猜一个。
    truncated: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class DraftPositionItem(BaseModel):
    """一条归一化后等待用户确认的草稿行."""

    raw_fund_name: str | None = None
    matched_fund_code: str | None = None
    matched_fund_name: str | None = None
    market_value: float | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    # 从截图一路带过来的标记：名称被 App 用省略号截断过，所以只有用户
    # 自己把基金挑定，这一行才可信。
    truncated: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    validation_status: str = "valid"
    validation_issues: list[str] = Field(default_factory=list)


class HoldingImportDraft(BaseModel):
    """任何 provider 的统一解析结果：草稿行 + 统计 + 错误信息."""

    items: list[DraftPositionItem] = Field(default_factory=list)
    image_count: int = 0
    image_hashes: list[str] = Field(default_factory=list)
    error_message: str | None = None


@runtime_checkable
class HoldingImportProvider(Protocol):
    """把原始载荷转成待确认草稿——绝不写持仓."""

    async def parse(self, payload: HoldingImportPayload) -> HoldingImportDraft:
        """把载荷解析成供复核的草稿."""
        ...
