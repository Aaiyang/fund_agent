"""Watchlist domain service."""

from datetime import datetime, timedelta

from app.core.logging import logger
from app.repositories.fund_repository import fund_repository
from app.repositories.watchlist_repository import watchlist_repository
from app.schemas.watchlist import WatchlistFundItem, WatchlistGroupItem
from app.utils.clock import utc_now

_NAV_FRESH_DAYS = 3


class WatchlistService:
    """Async watchlist operations shared by the API and future Agent tools."""

    async def list_funds(self, user_id: int, group_id: int | None = None) -> list[WatchlistFundItem]:
        """List watchlisted funds with market data, optionally scoped to a group.

        Args:
            user_id: Owner id.
            group_id: Optional group filter (None = all funds).

        Returns:
            Watchlist fund items ordered by sort_order.
        """
        entries = await watchlist_repository.list_funds(user_id)
        group_map = await watchlist_repository.list_group_map(user_id)
        if group_id is not None:
            entries = [
                entry for entry in entries if any(gid == group_id for gid, _ in group_map.get(entry.fund_code, []))
            ]

        codes = [entry.fund_code for entry in entries]
        funds = await fund_repository.get_funds(codes)
        navs = await fund_repository.get_latest_navs(codes)
        held_codes = await watchlist_repository.list_held_fund_codes(user_id)

        items: list[WatchlistFundItem] = []
        for entry in entries:
            fund = funds.get(entry.fund_code)
            latest = navs.get(entry.fund_code)
            groups = group_map.get(entry.fund_code, [])
            items.append(
                WatchlistFundItem(
                    fund_code=entry.fund_code,
                    fund_name=fund.fund_name if fund else entry.fund_code,
                    fund_type=fund.fund_type if fund else None,
                    latest_nav=latest.unit_nav if latest else None,
                    nav_date=latest.nav_date if latest else None,
                    daily_return=latest.daily_return if latest else None,
                    is_held=entry.fund_code in held_codes,
                    is_updated=self._nav_is_fresh(latest.fetched_at, latest.nav_date) if latest else False,
                    sort_order=entry.sort_order,
                    groups=[name for _, name in groups],
                    group_ids=[gid for gid, _ in groups],
                )
            )
        logger.info("watchlist_listed", user_id=user_id, count=len(items))
        return items

    async def add_fund(self, user_id: int, fund_code: str, group_ids: list[int] | None = None) -> bool:
        """Add a fund to the watchlist and optionally to groups.

        Returns:
            True on success; False when the fund code is unknown.
        """
        fund = await fund_repository.get_fund(fund_code)
        if fund is None:
            logger.info("watchlist_add_unknown_fund", user_id=user_id, fund_code=fund_code)
            return False
        await watchlist_repository.add_fund(user_id, fund_code)
        for group_id in group_ids or []:
            if await watchlist_repository.get_group(user_id, group_id) is not None:
                await watchlist_repository.add_to_group(user_id, group_id, fund_code)
        logger.info("watchlist_fund_added", user_id=user_id, fund_code=fund_code)
        return True

    async def remove_fund(self, user_id: int, fund_code: str) -> bool:
        """Remove a fund from the watchlist (and all groups)."""
        removed = await watchlist_repository.remove_fund(user_id, fund_code)
        logger.info("watchlist_fund_removed", user_id=user_id, fund_code=fund_code, removed=removed)
        return removed

    async def update_fund(
        self,
        user_id: int,
        fund_code: str,
        sort_order: int | None = None,
        group_ids: list[int] | None = None,
    ) -> bool:
        """Update sort order and/or replace group memberships for a watchlisted fund.

        Args:
            user_id: Owner id.
            fund_code: Watchlisted fund to edit.
            sort_order: New order within the watchlist.
            group_ids: Full desired membership — groups missing from the list
                drop the fund, so ungrouping is expressible (spec 3.3).

        Returns:
            False when the fund is not on the user's watchlist.
        """
        if sort_order is not None and await watchlist_repository.update_sort(user_id, fund_code, sort_order) is None:
            return False
        if group_ids is not None and not await watchlist_repository.set_fund_groups(user_id, fund_code, group_ids):
            return False
        logger.info("watchlist_fund_updated", user_id=user_id, fund_code=fund_code)
        return True

    async def list_groups(self, user_id: int) -> list[WatchlistGroupItem]:
        """List the user's groups with fund counts."""
        groups = await watchlist_repository.list_groups(user_id)
        group_map = await watchlist_repository.list_group_map(user_id)
        counts: dict[int, int] = {}
        for memberships in group_map.values():
            for group_id, _ in memberships:
                counts[group_id] = counts.get(group_id, 0) + 1
        return [
            WatchlistGroupItem(
                id=group.id or 0,
                name=group.name,
                sort_order=group.sort_order,
                fund_count=counts.get(group.id or 0, 0),
            )
            for group in groups
        ]

    async def create_group(self, user_id: int, name: str, sort_order: int = 0) -> WatchlistGroupItem:
        """Create a custom group."""
        group = await watchlist_repository.create_group(user_id, name, sort_order)
        logger.info("watchlist_group_created", user_id=user_id, group_id=group.id)
        return WatchlistGroupItem(id=group.id or 0, name=group.name, sort_order=group.sort_order)

    async def update_group(
        self,
        user_id: int,
        group_id: int,
        name: str | None = None,
        sort_order: int | None = None,
        fund_codes: list[str] | None = None,
    ) -> WatchlistGroupItem | None:
        """Rename or reorder a group, optionally rewriting its members and order.

        Args:
            user_id: Owner id.
            group_id: Group to edit.
            name: New display name.
            sort_order: New group order.
            fund_codes: Desired members in display order (spec 3.3 分组内排序).

        Returns:
            The updated group, or None when it does not exist.
        """
        group = await watchlist_repository.update_group(user_id, group_id, name, sort_order)
        if group is None:
            return None
        if fund_codes is not None and not await watchlist_repository.replace_group_members(
            user_id, group_id, fund_codes
        ):
            logger.warning("watchlist_group_reorder_partial", user_id=user_id, group_id=group_id)
        return WatchlistGroupItem(id=group.id or 0, name=group.name, sort_order=group.sort_order)

    async def delete_group(self, user_id: int, group_id: int) -> bool:
        """Delete a group; its funds stay watchlisted."""
        deleted = await watchlist_repository.delete_group(user_id, group_id)
        logger.info("watchlist_group_deleted", user_id=user_id, group_id=group_id, deleted=deleted)
        return deleted

    @staticmethod
    def _nav_is_fresh(fetched_at: datetime | None, nav_date) -> bool:
        """True when the NAV was fetched within the freshness window."""
        if fetched_at is None:
            return False
        fetched_naive = fetched_at.replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
        return fetched_naive >= utc_now() - timedelta(days=_NAV_FRESH_DAYS)


watchlist_service = WatchlistService()
