"""Portfolio API schemas (accounts, positions, transactions)."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.base import BaseResponse


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


class AccountUpdateRequest(BaseModel):
    """PATCH /accounts/{id} request."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    source_app: str | None = Field(default=None, max_length=50)


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
    daily_profit_loss: float | None = None
    daily_return: float | None = None
    position_ratio: float | None = None
    nav_date: date | None = None
    is_updated: bool = False
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
    """Manual create/update of a position snapshot (partial allowed)."""

    account_id: int
    shares: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    average_cost_nav: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    expected_version: int | None = Field(
        default=None,
        description="乐观锁：更新已有持仓时必传客户端读到的 version；不匹配返回 409",
    )


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
