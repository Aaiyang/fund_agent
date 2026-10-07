"""基金主数据与净值历史模型."""

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel
from app.utils.clock import utc_now


class Fund(BaseModel, table=True):
    """归一化后的基金主数据，由外部数据源同步而来.

    基金代码是天然的主键：自选、持仓、流水、导入记录这些下游实体都直接引用它。
    """

    fund_code: str = Field(primary_key=True, max_length=12, index=True)
    fund_name: str = Field(max_length=200, index=True)
    fund_type: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=200)
    manager_name: str | None = Field(default=None, max_length=200)
    inception_date: date | None = Field(default=None)
    # 快照口径的事实，照抄上游原文不做改写，例如规模写成 "226.75亿" 这种形式。
    asset_size: str | None = Field(default=None, max_length=50)

    # 数据血缘 —— 外部取回的每条事实都自带来源与时效
    source: str = Field(default="akshare", max_length=50)
    source_as_of: date | None = Field(default=None)
    fetched_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )


class FundNav(BaseModel, table=True):
    """基金净值历史行，按 (fund_code, nav_date) 唯一."""

    __tablename__ = "fund_nav"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    # 外键在数据库迁移里已经建好；这里照样声明出来，免得 Alembic autogenerate
    # 提议把它删掉。
    fund_code: str = Field(max_length=12, index=True, foreign_key="fund.fund_code")
    nav_date: date = Field(index=True)
    unit_nav: float | None = Field(default=None)
    accumulated_nav: float | None = Field(default=None)
    daily_return: float | None = Field(default=None)

    source: str = Field(default="akshare", max_length=50)
    fetched_at: datetime | None = Field(default=None)

    __table_args__ = (UniqueConstraint("fund_code", "nav_date", name="uq_fund_nav_code_date"),)
