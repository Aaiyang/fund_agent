"""Portfolio models: accounts, current positions, and transaction records."""

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel
from app.utils.clock import utc_now


class PortfolioAccount(BaseModel, table=True):
    """A user's fund holding account (e.g. 支付宝, 天天基金, 手工账户).

    source_app is only a label — it never represents a live third-party
    connection or stored third-party credentials.
    """

    __tablename__ = "portfolio_account"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    source_app: str | None = Field(default=None, max_length=50)
    account_type: str = Field(default="manual", max_length=30)
    import_mode: str = Field(default="manual", max_length=30)
    last_imported_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )

    # Two accounts of the same user never share a name: the picker lists them
    # by name only, so a duplicate is unreadable rather than merely untidy.
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_account_user_name"),)


class PortfolioPosition(BaseModel, table=True):
    """Current holdings snapshot for one fund inside one account.

    Snapshot semantics: imports and manual edits overwrite this row and bump
    `version`; derived metrics (rates, daily P/L, ratio) are computed at query
    time, never stored.
    """

    __tablename__ = "portfolio_position"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)

    shares: float | None = Field(default=None)
    cost_amount: float | None = Field(default=None)
    average_cost_nav: float | None = Field(default=None)
    market_value: float | None = Field(default=None)
    profit_loss: float | None = Field(default=None)

    # Optimistic lock — concurrent import vs manual edit returns 409, never silent overwrite
    version: int = Field(default=1)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )

    __table_args__ = (UniqueConstraint("account_id", "fund_code", name="uq_position_account_fund"),)


class Transaction(BaseModel, table=True):
    """Transaction or adjustment record.

    First-phase writes are audit-only: IMPORT_ADJUSTMENT rows produced by
    confirmed holdings imports. BUY/SELL/DIVIDEND/MANUAL_ADJUSTMENT exist as
    types for manual records and future features.
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)
    transaction_type: str = Field(max_length=30)
    trade_date: date = Field(index=True)
    shares: float | None = Field(default=None)
    nav: float | None = Field(default=None)
    amount: float | None = Field(default=None)
    fee: float | None = Field(default=None)
    source: str = Field(default="manual", max_length=50)
    external_transaction_id: str | None = Field(default=None, max_length=100)
