"""Watchlist models: user fund watchlist plus user-defined groups."""

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel


class Watchlist(BaseModel, table=True):
    """A user's watchlisted fund. Unique per (user_id, fund_code)."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    fund_code: str = Field(max_length=12, index=True)
    sort_order: int = Field(default=0)

    __table_args__ = (UniqueConstraint("user_id", "fund_code", name="uq_watchlist_user_fund"),)


class WatchlistGroup(BaseModel, table=True):
    """User-defined watchlist group (e.g. CPO, 创新药)."""

    __tablename__ = "watchlist_group"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    sort_order: int = Field(default=0)


class WatchlistGroupItem(BaseModel, table=True):
    """Association between a watchlist entry and a group."""

    __tablename__ = "watchlist_group_item"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="watchlist_group.id", index=True)
    watchlist_id: int = Field(foreign_key="watchlist.id", index=True)
    sort_order: int = Field(default=0)
