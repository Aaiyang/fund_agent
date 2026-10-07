"""持仓组合 API 的 schema（账户、持仓、流水）."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.analytics.positions import Direction, Operation
from app.schemas.base import BaseResponse, clean_required_text


# ---------------------------------------------------------------------------
# 账户
# ---------------------------------------------------------------------------


class AccountItem(BaseModel):
    """一个资产组合账户（source_app 只是一个标签）."""

    id: int
    name: str
    source_app: str | None = None
    account_type: str
    import_mode: str
    last_imported_at: datetime | None = None
    created_at: datetime | None = None


class AccountsResponse(BaseResponse):
    """GET /accounts 响应体."""

    items: list[AccountItem]
    total: int


class AccountCreateRequest(BaseModel):
    """POST /accounts 请求体."""

    name: str = Field(min_length=1, max_length=100)
    source_app: str | None = Field(default=None, max_length=50)
    account_type: str = Field(default="manual", max_length=30)
    import_mode: str = Field(default="manual", max_length=30)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return clean_required_text(value) or value


class AccountUpdateRequest(BaseModel):
    """PATCH /accounts/{id} 请求体."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    source_app: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return clean_required_text(value)


# ---------------------------------------------------------------------------
# 持仓
# ---------------------------------------------------------------------------


class PositionItem(BaseModel):
    """一笔持仓，派生指标在查询时算出（绝不落库）."""

    id: int | None = None
    account_id: int
    fund_code: str
    fund_name: str | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    market_value: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    # 标出上面哪几个金额是这行数据其实没存的：派生值不能回显进录入表单，
    # 冒充成用户亲自填过的数字。
    shares_derived: bool = False
    cost_derived: bool = False
    average_cost_nav_derived: bool = False
    profit_derived: bool = False
    daily_profit_loss: float | None = None
    daily_return: float | None = None
    unit_nav: float | None = None
    weekly_profit_loss: float | None = None
    monthly_profit_loss: float | None = None
    position_ratio: float | None = None
    nav_date: date | None = None
    is_updated: bool = False
    # 首次购买确认日：有流水时取最早的那笔 BUY，没有就沿用快照记下的值；
    # 持有天数从这一天开始算。
    purchase_date: date | None = None
    holding_days: int | None = None
    # 上面的份额和成本是由多少条 BUY/SELL 流水投影出来的。非 0 就意味着同步持仓
    # 不再有资格改写它们。
    trade_count: int = 0
    created_at: datetime | None = None
    version: int = 1
    updated_at: datetime | None = None


class PositionsResponse(BaseResponse):
    """GET /portfolio/positions 响应体."""

    items: list[PositionItem]
    total: int


class PortfolioSummary(BaseModel):
    """单个或全部账户的资产总览（spec 3.2）."""

    total_market_value: float = 0.0
    total_cost: float = 0.0
    total_profit_loss: float = 0.0
    total_profit_loss_rate: float | None = None
    daily_profit_loss: float = 0.0
    fund_count: int = 0
    data_updated_at: datetime | None = None


class PortfolioSummaryResponse(BaseResponse):
    """GET /portfolio/summary 响应体."""

    summary: PortfolioSummary
    accounts: list[AccountItem]


class PositionUpsertRequest(BaseModel):
    """同步持仓：按持仓页面显示的结果重述（允许只填一部分）.

    页面从不同侧读这些数字，配对方式并不唯一，所以表单给两种口径：持有金额配
    持有收益，持有份额配持仓成本价。任一组都能把四个金额全部定住；没当作输入
    的那项改为推算得出，原先存着的旧值随之作废。
    """

    account_id: int
    shares: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    average_cost_nav: float | None = Field(default=None, ge=0, description="持仓成本价，与份额配对")
    profit_loss: float | None = Field(default=None, description="持有收益，与金额配对")
    purchase_date: date | None = Field(default=None, description="首次购买确认日，持有天数从这天算")
    reset: list[Literal["shares", "average_cost_nav", "profit_loss"]] = Field(
        default_factory=list,
        description="把这些字段清空，回到由其余字段推算",
    )
    expected_version: int | None = Field(
        default=None,
        description="乐观锁：更新已有持仓时必传客户端读到的 version；不匹配返回 409",
    )


class TradeCreateRequest(BaseModel):
    """加减仓：记一笔买入、赎回、定投期数或转换."""

    account_id: int
    operation: Operation
    trade_date: date = Field(description="提交订单的那天")
    after_cutoff: bool = Field(default=False, description="是否 15:00 后提交，决定用哪一场净值")
    amount: float | None = Field(default=None, gt=0, description="买入/定投的成交金额")
    shares: float | None = Field(default=None, gt=0, description="卖出/转换份额")
    target_code: str | None = Field(default=None, min_length=6, max_length=6, description="转换目标基金")

    @model_validator(mode="after")
    def _order_carries_its_own_unit(self) -> "TradeCreateRequest":
        """进仓用金额定规模，出仓用份额定规模.

        转换还得指定转入的目标基金。这些值都没法从别处推出来，因此全部必填。
        """
        if self.operation in ("BUY", "AUTO_INVEST") and self.amount is None:
            raise ValueError("买入与定投需要填写金额")
        if self.operation in ("SELL", "CONVERT") and self.shares is None:
            raise ValueError("卖出与转换需要填写份额")
        if self.operation == "CONVERT" and not self.target_code:
            raise ValueError("转换需要选择目标基金")
        return self


class TradeLeg(BaseModel):
    """一笔订单在某只基金那一侧的腿，按确认日净值定价."""

    fund_code: str
    direction: Direction
    confirm_nav: float
    confirm_nav_date: date
    shares_delta: float
    amount: float
    shares_before: float
    cost_before: float
    shares_after: float
    cost_after: float


class TradePreviewResponse(BaseResponse):
    """GET .../trades/preview：这单会怎样改动持仓."""

    operation: Operation
    trade_date: date
    after_cutoff: bool
    # 订单定价所依据的那个交易日。只要越过截止点 15:00 或撞上非交易日，
    # 它就和 trade_date 不同。
    confirm_date: date
    legs: list[TradeLeg]


class PositionDeleteResponse(BaseModel):
    """DELETE 持仓的响应体."""

    deleted: bool


# ---------------------------------------------------------------------------
# 流水
# ---------------------------------------------------------------------------


class TransactionItem(BaseModel):
    """一条流水或一笔人工调整记录."""

    id: int
    account_id: int
    fund_code: str
    fund_name: str | None = None
    transaction_type: str
    trade_date: date
    # 订单定价所依据的交易日。只有交易流水带它：流水里的份额和成本就是按这天
    # 的净值记下来的。
    confirm_date: date | None = None
    shares: float | None = None
    nav: float | None = None
    amount: float | None = None
    fee: float | None = None
    source: str
    external_transaction_id: str | None = None
    created_at: datetime | None = None


class TransactionsResponse(BaseResponse):
    """GET /transactions 响应体."""

    items: list[TransactionItem]
    total: int
