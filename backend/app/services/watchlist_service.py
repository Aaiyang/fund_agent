"""Watchlist domain service."""

from datetime import date, datetime, timedelta

from app.analytics import period_return, window_return
from app.analytics.returns import NavPoint
from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.models.fund import Fund, FundNav
from app.repositories.fund_repository import fund_repository
from app.repositories.watchlist_repository import watchlist_repository
from app.schemas.watchlist import WatchlistFundItem, WatchlistGroupItem
from app.services.fund_sync_service import fund_sync_service
from app.utils.clock import business_today, utc_now

_NAV_FRESH_DAYS = 3
# Covers the longest column the list reports (近1年) plus a stale NAV grace period.
_HISTORY_LOOKBACK_DAYS = 400
_WEEKLY_DAYS = 7
# A series shorter than the longest displayed window means the fund was only ever
# reached through search, so its history still has to be pulled.
_BACKFILL_WINDOW_DAYS = 366
# One backfill request per fund per day; the sync lock dedups the job itself.
_BACKFILL_COOLDOWN_SECONDS = 24 * 3600


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
        history = await fund_repository.get_nav_history_map(
            codes, business_today() - timedelta(days=_HISTORY_LOOKBACK_DAYS)
        )

        items: list[WatchlistFundItem] = []
        thin_codes: list[str] = []
        for entry in entries:
            fund = funds.get(entry.fund_code)
            latest = navs.get(entry.fund_code)
            groups = group_map.get(entry.fund_code, [])
            rows = history.get(entry.fund_code, [])
            if latest is not None and self._series_is_thin(rows, latest.nav_date, fund):
                thin_codes.append(entry.fund_code)
            items.append(
                WatchlistFundItem(
                    fund_code=entry.fund_code,
                    fund_name=fund.fund_name if fund else entry.fund_code,
                    fund_type=fund.fund_type if fund else None,
                    latest_nav=latest.unit_nav if latest else None,
                    nav_date=latest.nav_date if latest else None,
                    daily_return=latest.daily_return if latest else None,
                    **self._period_metrics(rows, latest),
                    is_held=entry.fund_code in held_codes,
                    is_updated=self._nav_is_fresh(latest.fetched_at, latest.nav_date) if latest else False,
                    sort_order=entry.sort_order,
                    groups=[name for _, name in groups],
                    group_ids=[gid for gid, _ in groups],
                )
            )
        if thin_codes:
            await self._request_history_backfill(thin_codes)
        logger.info("watchlist_listed", user_id=user_id, count=len(items), backfill=thin_codes)
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
    def _series_is_thin(rows: list[FundNav], end: date, fund: Fund | None) -> bool:
        """True when the stored series cannot reach back over the longest window.

        A fund reached only through search has a single NAV row, which leaves
        the period columns empty until the history lands. Funds younger than the
        window are excluded: no sync can produce their missing rows.
        """
        window_start = end - timedelta(days=_BACKFILL_WINDOW_DAYS)
        if fund is not None and fund.inception_date is not None and fund.inception_date > window_start:
            return False
        return not rows or rows[0].nav_date > window_start

    async def _request_history_backfill(self, fund_codes: list[str]) -> None:
        """Ask the queue to pull NAV history for funds with thin series.

        The read stays non-blocking: the broker runs the job outside the
        request, so the next list load fills in the missing columns.
        """
        today = business_today().isoformat()
        for fund_code in fund_codes:
            if not await cache_service.acquire_lock(
                cache_key("watchlist_history_backfill", fund_code, today), ttl=_BACKFILL_COOLDOWN_SECONDS
            ):
                continue
            try:
                await fund_sync_service.enqueue_sync(fund_code)
            except Exception as e:
                logger.warning("watchlist_history_backfill_failed", fund_code=fund_code, error=str(e))

    @staticmethod
    def _period_metrics(rows: list[FundNav], latest: FundNav | None) -> dict[str, float | None]:
        """Trailing 1-week/1/3/6/12-month returns, in percent points.

        The analytics helpers return fractions while the `daily_return` column
        already holds percent points; both are reported in the column's unit so
        one formatter handles the whole row (MVP spec 5.2).
        """
        fields = ("weekly_return", "monthly_return", "quarterly_return", "semiannual_return", "annual_return")
        if latest is None:
            return dict.fromkeys(fields)
        points = [NavPoint(row.nav_date, row.unit_nav) for row in rows if row.unit_nav is not None]
        end = latest.nav_date

        def as_points(fraction: float | None) -> float | None:
            return None if fraction is None else round(fraction * 100, 4)

        return {
            "weekly_return": as_points(window_return(points, end, _WEEKLY_DAYS)),
            "monthly_return": as_points(period_return(points, end, 1)),
            "quarterly_return": as_points(period_return(points, end, 3)),
            "semiannual_return": as_points(period_return(points, end, 6)),
            "annual_return": as_points(period_return(points, end, 12)),
        }

    @staticmethod
    def _nav_is_fresh(fetched_at: datetime | None, nav_date) -> bool:
        """True when the NAV was fetched within the freshness window."""
        if fetched_at is None:
            return False
        fetched_naive = fetched_at.replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
        return fetched_naive >= utc_now() - timedelta(days=_NAV_FRESH_DAYS)


watchlist_service = WatchlistService()
