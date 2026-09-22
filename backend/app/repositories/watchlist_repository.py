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

    async def list_held_fund_codes(self, user_id: int) -> set[str]:
        """Fund codes the user holds anywhere, for one bulk lookup."""
        async with get_async_session() as session:
            rows = (
                (
                    await session.execute(
                        select(col(PortfolioPosition.fund_code))
                        .where(col(PortfolioPosition.user_id) == user_id)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            return set(rows)

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

    async def list_group_map(self, user_id: int) -> dict[str, list[tuple[int, str]]]:
        """Map fund code → [(group_id, group_name)] for every watchlisted fund.

        One join instead of one query per row, and it keeps group order as the
        user set it (``watchlist_group_item.sort_order``).
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(
                    col(Watchlist.fund_code),
                    col(WatchlistGroup.id),
                    col(WatchlistGroup.name),
                )
                .join(WatchlistGroupItem, col(WatchlistGroupItem.watchlist_id) == Watchlist.id)
                .join(WatchlistGroup, col(WatchlistGroup.id) == WatchlistGroupItem.group_id)
                .where(col(Watchlist.user_id) == user_id)
                .order_by(col(WatchlistGroupItem.sort_order), col(WatchlistGroupItem.id))
            )
            grouped: dict[str, list[tuple[int, str]]] = {}
            for fund_code, group_id, name in result:
                grouped.setdefault(fund_code, []).append((group_id, name))
            return grouped

    async def replace_group_members(self, user_id: int, group_id: int, fund_codes: list[str]) -> bool | None:
        """Set a group's membership and in-group order (spec 3.3 排序).

        Args:
            user_id: Owner id — the group must belong to the caller.
            group_id: Group to rewrite.
            fund_codes: Desired members, in display order. Codes the user has
                not watchlisted are ignored.

        Returns:
            True when updated, False when some code was not watchlisted,
            None when the group does not exist.
        """
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

            entries = (
                (
                    await session.execute(
                        select(Watchlist).where(
                            col(Watchlist.user_id) == user_id, col(Watchlist.fund_code).in_(fund_codes)
                        )
                    )
                )
                .scalars()
                .all()
            )
            entry_ids = {entry.fund_code: entry.id for entry in entries if entry.id is not None}

            existing = (
                (await session.execute(select(WatchlistGroupItem).where(col(WatchlistGroupItem.group_id) == group_id)))
                .scalars()
                .all()
            )
            existing_by_watchlist = {item.watchlist_id: item for item in existing}

            wanted_ids = {entry_ids[code] for code in fund_codes if code in entry_ids}
            for watchlist_id, item in existing_by_watchlist.items():
                if watchlist_id not in wanted_ids:
                    await session.delete(item)

            for position, code in enumerate(fund_codes):
                watchlist_id = entry_ids.get(code)
                if watchlist_id is None:
                    continue
                item = existing_by_watchlist.get(watchlist_id)
                if item is None:
                    session.add(WatchlistGroupItem(group_id=group_id, watchlist_id=watchlist_id, sort_order=position))
                else:
                    item.sort_order = position
                    session.add(item)
            await session.flush()
            return len(wanted_ids) == len([code for code in fund_codes if code in entry_ids])

    async def set_fund_groups(self, user_id: int, fund_code: str, group_ids: list[int]) -> bool:
        """Replace which groups a watchlisted fund belongs to.

        Returns:
            True when the fund is watchlisted (even if no group changed),
            False when the watchlist entry does not exist.
        """
        async with get_async_session() as session:
            entry = (
                await session.execute(
                    select(Watchlist).where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code)
                )
            ).scalar_one_or_none()
            if entry is None or entry.id is None:
                return False

            owned_groups = set(
                (
                    await session.execute(
                        select(col(WatchlistGroup.id)).where(
                            col(WatchlistGroup.user_id) == user_id, col(WatchlistGroup.id).in_(group_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            items = (
                (
                    await session.execute(
                        select(WatchlistGroupItem).where(col(WatchlistGroupItem.watchlist_id) == entry.id)
                    )
                )
                .scalars()
                .all()
            )
            current = {item.group_id: item for item in items}

            for group_id, item in current.items():
                if group_id not in owned_groups:
                    await session.delete(item)
            for position, group_id in enumerate(group_ids):
                if group_id not in owned_groups:
                    continue
                item = current.get(group_id)
                if item is None:
                    session.add(WatchlistGroupItem(group_id=group_id, watchlist_id=entry.id, sort_order=position))
            await session.flush()
            return True


watchlist_repository = WatchlistRepository()
