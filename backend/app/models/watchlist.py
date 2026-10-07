"""自选模型：用户自选基金与用户自定义的自选分组."""

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel


class Watchlist(BaseModel, table=True):
    """用户加入自选的一只基金，按 (user_id, fund_code) 唯一."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    fund_code: str = Field(max_length=12, index=True)
    sort_order: int = Field(default=0)

    __table_args__ = (UniqueConstraint("user_id", "fund_code", name="uq_watchlist_user_fund"),)


class WatchlistGroup(BaseModel, table=True):
    """用户自定义的自选分组（例如 CPO、创新药）."""

    __tablename__ = "watchlist_group"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    sort_order: int = Field(default=0)


class WatchlistGroupItem(BaseModel, table=True):
    """自选条目与分组之间的关联."""

    __tablename__ = "watchlist_group_item"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="watchlist_group.id", index=True)
    watchlist_id: int = Field(foreign_key="watchlist.id", index=True)
    sort_order: int = Field(default=0)
