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
    """Current holdings for one fund inside one account.

    ``shares`` and ``cost_amount`` are a projection of the fund's BUY/SELL
    ledger whenever that ledger has rows — the trade write recomputes both.
    Without a ledger they are whatever 同步持仓 recorded. ``market_value`` is
    always the snapshot figure, so correcting it never touches the ledger.
    Derived metrics (rates, daily P/L, ratio) are computed at query time.
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

    # When the purchase was confirmed. Funds price an order at that day's NAV
    # before 15:00 and the next session's after, so the cutoff is resolved into
    # this date at write time instead of being stored as a clock time the user
    # would have to guess at. With a ledger it is the earliest BUY's confirm
    # day, which is where 持有天数 counts from.
    purchase_date: date | None = Field(default=None)

    # Optimistic lock — concurrent import vs manual edit returns 409, never silent overwrite
    version: int = Field(default=1)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )

    __table_args__ = (UniqueConstraint("account_id", "fund_code", name="uq_position_account_fund"),)


class AutoInvestPlan(BaseModel, table=True):
    """A standing instruction to buy a fixed amount on a repeating day.

    The platform debits the money, not this app; the plan is what the user says
    he set up, and settling it writes ordinary purchase rows so the holding's
    ledger stays the single source for 份额 and 成本.
    """

    __tablename__ = "auto_invest_plan"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)

    amount: float = Field()
    frequency: str = Field(default="weekly", max_length=20)
    # weekly/biweekly: ISO weekday 1-7. monthly: day of month, clamped to the
    # last day in short months the way the platforms do it.
    run_day: int = Field(default=1)
    start_date: date
    end_date: date | None = Field(default=None)
    active: bool = Field(default=True)
    # The latest scheduled day already written as a purchase. Keeping it makes
    # catching up after a long gap idempotent.
    last_run_date: date | None = Field(default=None)

    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )


class Transaction(BaseModel, table=True):
    """Transaction or adjustment record.

    BUY and SELL rows are the ledger a position is projected from, so they
    carry the resolved ``confirm_date`` and the NAV the units were priced at.
    IMPORT_ADJUSTMENT and MANUAL_ADJUSTMENT rows are audit-only: they record
    what a snapshot overwrite replaced and never move the projection.
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)
    transaction_type: str = Field(max_length=30)
    trade_date: date = Field(index=True)
    # The session the order was priced against: trade_date, or the next one
    # when it was submitted after 15:00 or on a non-trading day.
    confirm_date: date | None = Field(default=None)
    shares: float | None = Field(default=None)
    nav: float | None = Field(default=None)
    amount: float | None = Field(default=None)
    fee: float | None = Field(default=None)
    source: str = Field(default="manual", max_length=50)
    external_transaction_id: str | None = Field(default=None, max_length=100)
