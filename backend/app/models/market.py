"""公开行情参考数据：业绩比较基准指数的收盘点位."""

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel


class IndexQuote(BaseModel, table=True):
    """基准指数在某一交易日的收盘点位."""

    __tablename__ = "index_quote"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    index_code: str = Field(max_length=12, index=True)
    trade_date: date = Field(index=True)
    close: float
    source: str = Field(default="akshare", max_length=50)
    fetched_at: datetime | None = Field(default=None)

    __table_args__ = (UniqueConstraint("index_code", "trade_date", name="uq_index_quote_code_date"),)
