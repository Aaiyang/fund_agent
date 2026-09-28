"""Portfolio API schemas (accounts, positions, transactions)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.analytics.positions import Direction, Operation
from app.schemas.base import BaseResponse, clean_required_text


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class AccountItem(BaseModel):
    """One portfolio account (source_app is only a label)."""

    id: int
    name: str
    source_app: str | None = None
    account_type: str
    import_mode: str
    last_imported_at: datetime | None = None
    created_at: datetime | None = None


class AccountsResponse(BaseResponse):
    """GET /accounts response."""

    items: list[AccountItem]
    total: int


class AccountCreateRequest(BaseModel):
    """POST /accounts request."""

    name: str = Field(min_length=1, max_length=100)
    source_app: str | None = Field(default=None, max_length=50)
    account_type: str = Field(default="manual", max_length=30)
    import_mode: str = Field(default="manual", max_length=30)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return clean_required_text(value) or value


class AccountUpdateRequest(BaseModel):
    """PATCH /accounts/{id} request."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    source_app: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return clean_required_text(value)


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class PositionItem(BaseModel):
    """One holding with query-time derived metrics (never stored)."""

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
    # Which of the figures above the row does not actually store: a derived one
    # must not be echoed back into the entry form as if the user had asserted it.
    shares_derived: bool = False
    cost_derived: bool = False
    profit_derived: bool = False
    daily_profit_loss: float | None = None
    daily_return: float | None = None
    unit_nav: float | None = None
    weekly_profit_loss: float | None = None
    monthly_profit_loss: float | None = None
    position_ratio: float | None = None
    nav_date: date | None = None
    is_updated: bool = False
    # 首次购买确认日: the earliest BUY when there is a ledger, else whatever the
    # snapshot recorded. 持有天数 counts from it.
    purchase_date: date | None = None
    holding_days: int | None = None
    # How many BUY/SELL rows the shares and cost above were projected from.
    # Non-zero means 同步持仓 may no longer restate them.
    trade_count: int = 0
    created_at: datetime | None = None
    version: int = 1
    updated_at: datetime | None = None


class PositionsResponse(BaseResponse):
    """GET /portfolio/positions response."""

    items: list[PositionItem]
    total: int


class PortfolioSummary(BaseModel):
    """Asset summary across one or all accounts (spec 3.2)."""

    total_market_value: float = 0.0
    total_cost: float = 0.0
    total_profit_loss: float = 0.0
    total_profit_loss_rate: float | None = None
    daily_profit_loss: float = 0.0
    fund_count: int = 0
    data_updated_at: datetime | None = None


class PortfolioSummaryResponse(BaseResponse):
    """GET /portfolio/summary response."""

    summary: PortfolioSummary
    accounts: list[AccountItem]


class PositionUpsertRequest(BaseModel):
    """同步持仓: restate what a holdings screen shows (partial allowed).

    持仓成本 and 平均成本净值 are not inputs — both follow from 持有金额 minus
    持有收益, and a stored cost would otherwise outrank a profit he restates.
    On a fund with a BUY/SELL ledger the service also drops 份额/收益 here,
    because those belong to the trade records.
    """

    account_id: int
    shares: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    purchase_date: date | None = Field(default=None, description="首次购买确认日，持有天数从这天算")
    reset: list[Literal["shares", "profit_loss"]] = Field(
        default_factory=list,
        description="把这些字段清空，回到由其余字段推算",
    )
    expected_version: int | None = Field(
        default=None,
        description="乐观锁：更新已有持仓时必传客户端读到的 version；不匹配返回 409",
    )


class TradeCreateRequest(BaseModel):
    """加减仓: record one purchase, redemption, installment or conversion."""

    account_id: int
    operation: Operation
    trade_date: date = Field(description="提交订单的那天")
    after_cutoff: bool = Field(default=False, description="是否 15:00 后提交，决定用哪一场净值")
    amount: float | None = Field(default=None, gt=0, description="买入/定投金额（含申购费）")
    shares: float | None = Field(default=None, gt=0, description="卖出/转换份额")
    fee: float | None = Field(default=None, ge=0, description="申购费/赎回费/转换费")
    target_code: str | None = Field(default=None, min_length=6, max_length=6, description="转换目标基金")

    @model_validator(mode="after")
    def _order_carries_its_own_unit(self) -> "TradeCreateRequest":
        """Money sizes the buys, shares size the exits.

        A conversion also names the fund to arrive in. None of it is inferable,
        so all of it is required.
        """
        if self.operation in ("BUY", "AUTO_INVEST") and self.amount is None:
            raise ValueError("买入与定投需要填写金额")
        if self.operation in ("SELL", "CONVERT") and self.shares is None:
            raise ValueError("卖出与转换需要填写份额")
        if self.operation == "CONVERT" and not self.target_code:
            raise ValueError("转换需要选择目标基金")
        return self


class TradeLeg(BaseModel):
    """One fund's side of an order, priced on the confirm day."""

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
    """GET .../trades/preview: what this order would do to the holding."""

    operation: Operation
    trade_date: date
    after_cutoff: bool
    # The session the order is priced against. It differs from trade_date
    # whenever the cutoff or a non-trading day moved the order along.
    confirm_date: date
    fee: float
    legs: list[TradeLeg]


class PositionDeleteResponse(BaseModel):
    """DELETE position response."""

    deleted: bool


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionItem(BaseModel):
    """One transaction or adjustment record."""

    id: int
    account_id: int
    fund_code: str
    fund_name: str | None = None
    transaction_type: str
    trade_date: date
    # The session an order was priced against. Only trades carry it; it is the
    # day the ledger's shares and cost were bought at.
    confirm_date: date | None = None
    shares: float | None = None
    nav: float | None = None
    amount: float | None = None
    fee: float | None = None
    source: str
    external_transaction_id: str | None = None
    created_at: datetime | None = None


class TransactionsResponse(BaseResponse):
    """GET /transactions response."""

    items: list[TransactionItem]
    total: int
