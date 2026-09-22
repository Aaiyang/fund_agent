"""Fund master data and NAV history models."""

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel
from app.utils.clock import utc_now


class Fund(BaseModel, table=True):
    """Standardized fund master data, synced from external providers.

    The fund code is the natural primary key: all downstream entities
    (watchlists, positions, transactions, imports) reference it directly.
    """

    fund_code: str = Field(primary_key=True, max_length=12, index=True)
    fund_name: str = Field(max_length=200, index=True)
    fund_type: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=200)
    manager_name: str | None = Field(default=None, max_length=200)
    inception_date: date | None = Field(default=None)
    # Snapshot facts quoted verbatim from the source: a size like "226.75亿" and
    # the fund's own stated comparison benchmark.
    asset_size: str | None = Field(default=None, max_length=50)
    benchmark: str | None = Field(default=None, max_length=300)

    # Data lineage — every external fact keeps its source and freshness
    source: str = Field(default="akshare", max_length=50)
    source_as_of: date | None = Field(default=None)
    fetched_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )


class FundNav(BaseModel, table=True):
    """Historical fund NAV rows, unique per (fund_code, nav_date)."""

    __tablename__ = "fund_nav"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    fund_code: str = Field(max_length=12, index=True)
    nav_date: date = Field(index=True)
    unit_nav: float | None = Field(default=None)
    accumulated_nav: float | None = Field(default=None)
    daily_return: float | None = Field(default=None)

    source: str = Field(default="akshare", max_length=50)
    fetched_at: datetime | None = Field(default=None)

    __table_args__ = (UniqueConstraint("fund_code", "nav_date", name="uq_fund_nav_code_date"),)
