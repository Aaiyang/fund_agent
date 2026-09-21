"""Watchlist repository: watchlist entries, groups and group items."""

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlmodel import col

from app.core.database import get_async_session
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist, WatchlistGroup, WatchlistGroupItem


class WatchlistRepository:
    """Async data access for the user's watchlist and its groups."""

    # ------------------------------------------------------------------
    # Watchlist entries
    # ------------------------------------------------------------------

    async def list_funds(self, user_id: int) -> list[Watchlist]:
        """List the user's watchlisted funds ordered by sort_order."""
        async with get_async_session() as session:
            statement = (
                select(Watchlist)
                .where(col(Watchlist.user_id) == user_id)
                .order_by(col(Watchlist.sort_order), col(Watchlist.id))
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def add_fund(self, user_id: int, fund_code: str) -> Watchlist:
        """Add a fund to the watchlist (idempotent)."""
        async with get_async_session() as session:
            existing = (
                await session.execute(
                    select(Watchlist).where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
            entry = Watchlist(user_id=user_id, fund_code=fund_code)
            session.add(entry)
            await session.flush()
            return entry

    async def remove_fund(self, user_id: int, fund_code: str) -> bool:
        """Remove a fund (and its group memberships). Returns True if removed."""
        async with get_async_session() as session:
            entry = (
                await session.execute(
                    select(Watchlist).where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code)
                )
            ).scalar_one_or_none()
            if entry is None:
                return False
            await session.execute(
                sa_delete(WatchlistGroupItem).where(col(WatchlistGroupItem.watchlist_id) == entry.id)
            )
            await session.delete(entry)
            return True

    async def update_sort(self, user_id: int, fund_code: str, sort_order: int) -> Watchlist | None:
        """Update a fund's sort order within the watchlist."""
        async with get_async_session() as session:
            entry = (
                await session.execute(
                    select(Watchlist).where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code)
                )
            ).scalar_one_or_none()
            if entry is None:
                return None
            entry.sort_order = sort_order
            session.add(entry)
            await session.flush()
            return entry

    async def is_watchlisted(self, user_id: int, fund_code: str) -> bool:
        """Whether the user watchlists this fund."""
        async with get_async_session() as session:
            row = (
                await session.execute(
                    select(col(Watchlist.id)).where(
                        col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code
                    )
                )
            ).first()
            return row is not None

    async def is_held(self, user_id: int, fund_code: str) -> bool:
        """Whether the user holds this fund anywhere."""
        async with get_async_session() as session:
            row = (
                await session.execute(
                    select(col(PortfolioPosition.id)).where(
                        col(PortfolioPosition.user_id) == user_id, col(PortfolioPosition.fund_code) == fund_code
                    )
                )
            ).first()
            return row is not None

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    async def list_groups(self, user_id: int) -> list[WatchlistGroup]:
        """List the user's watchlist groups ordered by sort_order."""
        async with get_async_session() as session:
            result = await session.execute(
                select(WatchlistGroup)
                .where(col(WatchlistGroup.user_id) == user_id)
                .order_by(col(WatchlistGroup.sort_order), col(WatchlistGroup.id))
            )
            return list(result.scalars().all())

    async def get_group(self, user_id: int, group_id: int) -> WatchlistGroup | None:
        """Load one group owned by the user."""
        async with get_async_session() as session:
            result = await session.execute(
                select(WatchlistGroup).where(
                    col(WatchlistGroup.id) == group_id, col(WatchlistGroup.user_id) == user_id
                )
            )
            return result.scalar_one_or_none()

    async def create_group(self, user_id: int, name: str, sort_order: int = 0) -> WatchlistGroup:
        """Create a custom watchlist group."""
        async with get_async_session() as session:
            group = WatchlistGroup(user_id=user_id, name=name, sort_order=sort_order)
            session.add(group)
            await session.flush()
            return group

    async def update_group(
        self,
        user_id: int,
        group_id: int,
        name: str | None = None,
        sort_order: int | None = None,
    ) -> WatchlistGroup | None:
        """Rename or reorder a group."""
        async with get_async_session() as session:
            group = (
                await session.execute(
                    select(WatchlistGroup).where(
                        col(WatchlistGroup.id) == group_id, col(WatchlistGroup.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if group is None:
                return None
            if name is not None:
                group.name = name
            if sort_order is not None:
                group.sort_order = sort_order
            session.add(group)
            await session.flush()
            return group

    async def delete_group(self, user_id: int, group_id: int) -> bool:
        """Delete a group and its item associations."""
        async with get_async_session() as session:
            group = (
                await session.execute(
                    select(WatchlistGroup).where(
                        col(WatchlistGroup.id) == group_id, col(WatchlistGroup.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if group is None:
                return False
            await session.execute(sa_delete(WatchlistGroupItem).where(col(WatchlistGroupItem.group_id) == group_id))
            await session.delete(group)
            return True

    async def list_group_fund_codes(self, group_id: int) -> list[str]:
        """Fund codes inside a group, ordered by item sort_order."""
        async with get_async_session() as session:
            result = await session.execute(
                select(col(Watchlist.fund_code))
                .join(WatchlistGroupItem, col(WatchlistGroupItem.watchlist_id) == Watchlist.id)
                .where(col(WatchlistGroupItem.group_id) == group_id)
                .order_by(col(WatchlistGroupItem.sort_order), col(WatchlistGroupItem.id))
            )
            return [row[0] for row in result]

    async def add_to_group(self, user_id: int, group_id: int, fund_code: str) -> WatchlistGroupItem | None:
        """Add a watchlisted fund to a group (idempotent)."""
        async with get_async_session() as session:
            entry = (
                await session.execute(
                    select(Watchlist).where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code)
                )
            ).scalar_one_or_none()
            if entry is None or entry.id is None:
                return None
            existing = (
                await session.execute(
                    select(WatchlistGroupItem).where(
                        col(WatchlistGroupItem.group_id) == group_id, col(WatchlistGroupItem.watchlist_id) == entry.id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
            item = WatchlistGroupItem(group_id=group_id, watchlist_id=entry.id)
            session.add(item)
            await session.flush()
            return item

    async def remove_from_group(self, group_id: int, fund_code: str) -> bool:
        """Remove a fund from a group."""
        async with get_async_session() as session:
            result = await session.execute(
                select(WatchlistGroupItem)
                .join(Watchlist, col(Watchlist.id) == WatchlistGroupItem.watchlist_id)
                .where(col(WatchlistGroupItem.group_id) == group_id, col(Watchlist.fund_code) == fund_code)
            )
            item = result.scalars().first()
            if item is None:
                return False
            await session.delete(item)
            return True


watchlist_repository = WatchlistRepository()
