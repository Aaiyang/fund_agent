"""Holding import models: import batches and their pending items.

These tables drive the parse → review → confirm → apply flow. They are an
audit surface — the authoritative holdings fact table is portfolio_position.
Raw screenshot images are never stored here (or anywhere in PostgreSQL).
"""

from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, JSON

from app.models.base import BaseModel
from app.utils.clock import utc_now


def _new_import_id() -> str:
    return uuid4().hex


class HoldingImport(BaseModel, table=True):
    """One manual or screenshot holdings import batch.

    Status lifecycle: UPLOADED → PARSING → REVIEW_REQUIRED → CONFIRMED →
    APPLIED, with PARSE_FAILED / CANCELLED as terminal error states.
    """

    __tablename__ = "holding_import"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=_new_import_id, primary_key=True, max_length=32)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    import_type: str = Field(max_length=20)  # MANUAL / SCREENSHOT
    source_app: str | None = Field(default=None, max_length=50)
    status: str = Field(default="UPLOADED", max_length=30, index=True)

    image_count: int = Field(default=0)
    image_hashes: list | dict | None = Field(default=None, sa_type=JSON)
    items_detected: int = Field(default=0)
    items_confirmed: int = Field(default=0)

    error_message: str | None = Field(default=None, max_length=500)
    started_at: datetime | None = Field(default=None)
    confirmed_at: datetime | None = Field(default=None)
    applied_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )


class HoldingImportItem(BaseModel, table=True):
    """One pending holdings entry awaiting user confirmation.

    user_action records the user's decision: UPDATE (import), SKIP, or EDIT
    (user corrected fields before confirming).
    """

    __tablename__ = "holding_import_item"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    import_id: str = Field(foreign_key="holding_import.id", index=True)
    raw_fund_name: str | None = Field(default=None, max_length=200)
    matched_fund_code: str | None = Field(default=None, max_length=12, index=True)
    matched_fund_name: str | None = Field(default=None, max_length=200)

    market_value: float | None = Field(default=None)
    shares: float | None = Field(default=None)
    cost_amount: float | None = Field(default=None)
    average_cost_nav: float | None = Field(default=None)
    profit_loss: float | None = Field(default=None)
    profit_loss_rate: float | None = Field(default=None)

    confidence: float | None = Field(default=None)
    validation_status: str = Field(default="pending", max_length=30)
    validation_issues: list | dict | None = Field(default=None, sa_type=JSON)
    user_action: str | None = Field(default=None, max_length=20)
