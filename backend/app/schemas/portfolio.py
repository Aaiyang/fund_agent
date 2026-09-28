"""Portfolio API schemas (accounts, positions, transactions)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    # Which of the two above the row actually stores: a derived figure must not
    # be echoed back into the entry form as if the user had asserted it.
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
    purchase_date: date | None = None
    purchase_after_cutoff: bool = False
    # The session whose NAV the purchase was priced against, derived from the
    # cutoff; 持有天数 counts from it.
    settlement_date: date | None = None
    holding_days: int | None = None
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
    """Manual create/update of a position snapshot (partial allowed).

    份额 and 平均成本净值 are deliberately absent: both follow from 持有金额 plus
    the NAV the purchase settled on, so accepting them by hand would let a
    stale guess override the arithmetic.
    """

    account_id: int
    cost_amount: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    purchase_date: date | None = None
    purchase_after_cutoff: bool | None = None
    reset: list[Literal["cost_amount", "profit_loss"]] = Field(
        default_factory=list,
        description="把这些字段改回系统推算：清空已存值，之后由确认日净值推出",
    )
    expected_version: int | None = Field(
        default=None,
        description="乐观锁：更新已有持仓时必传客户端读到的 version；不匹配返回 409",
    )


class PositionPreviewResponse(BaseResponse):
    """GET /portfolio/positions/preview: what a purchase date implies."""

    fund_code: str
    purchase_date: date
    purchase_after_cutoff: bool
    settlement_date: date
    holding_days: int
    # The two NAVs the estimate is made of, with the day each was published on
    # so a missing row reads as "还没有那天的净值" instead of a silent blank.
    settled_nav: float | None = None
    settled_nav_date: date | None = None
    unit_nav: float | None = None
    nav_date: date | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None


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
