"""自选域服务."""

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
# 覆盖列表里最长的一个区间（近1年），再留一段净值过期的宽限期。
_HISTORY_LOOKBACK_DAYS = 400
_WEEKLY_DAYS = 7
# 序列比展示的最长区间还短，说明这只基金只是搜索时顺带进来的，
# 它的历史仍然需要补拉一次。
_BACKFILL_WINDOW_DAYS = 366
# 每只基金每天只请求一次回填；任务本身由同步锁去重。
_BACKFILL_COOLDOWN_SECONDS = 24 * 3600


class WatchlistService:
    """供 API 与后续 Agent 工具共用的异步自选操作."""

    async def list_funds(self, user_id: int, group_id: int | None = None) -> list[WatchlistFundItem]:
        """列出自选基金及其行情，可以只看某一个分组.

        Args:
            user_id: 所属用户 id。
            group_id: 可选的分组过滤（None 表示全部基金）。

        Returns:
            按 sort_order 排好的自选基金项。
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
        """把基金加进自选，可以顺带加进若干分组.

        Returns:
            成功返回 True；基金代码不存在返回 False。
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
        """把基金从自选里移除（同时移出所有分组）."""
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
        """修改自选基金的排序，和/或整体替换它的分组归属.

        Args:
            user_id: 所属用户 id。
            fund_code: 要编辑的自选基金。
            sort_order: 在自选列表里的新顺序。
            group_ids: 期望的完整归属 —— 没出现在这份列表里的分组，
                会把这只基金移出去，所以取消分组也能表达（spec 3.3）。

        Returns:
            该基金不在用户自选里时返回 False。
        """
        if sort_order is not None and await watchlist_repository.update_sort(user_id, fund_code, sort_order) is None:
            return False
        if group_ids is not None and not await watchlist_repository.set_fund_groups(user_id, fund_code, group_ids):
            return False
        logger.info("watchlist_fund_updated", user_id=user_id, fund_code=fund_code)
        return True

    async def list_groups(self, user_id: int) -> list[WatchlistGroupItem]:
        """列出用户的分组，以及各组的基金数量."""
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
        """创建自定义分组."""
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
        """给分组改名或排序，也可以顺带重写组内成员及成员顺序.

        Args:
            user_id: 所属用户 id。
            group_id: 要编辑的分组。
            name: 新的展示名称。
            sort_order: 分组之间的新顺序。
            fund_codes: 期望的成员，按展示顺序给出（spec 3.3 分组内排序）。

        Returns:
            更新后的分组；分组不存在时返回 None。
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
        """删除分组；组里的基金仍然留在自选里."""
        deleted = await watchlist_repository.delete_group(user_id, group_id)
        logger.info("watchlist_group_deleted", user_id=user_id, group_id=group_id, deleted=deleted)
        return deleted

    @staticmethod
    def _series_is_thin(rows: list[FundNav], end: date, fund: Fund | None) -> bool:
        """落库序列撑不到最长区间之前时返回 True.

        只在搜索里出现过的基金只有一条净值行，
        区间收益那几列会一直空着，直到历史补齐为止。
        成立晚于该窗区的基金要排除：任何同步都变不出它们缺失的行。
        """
        window_start = end - timedelta(days=_BACKFILL_WINDOW_DAYS)
        if fund is not None and fund.inception_date is not None and fund.inception_date > window_start:
            return False
        return not rows or rows[0].nav_date > window_start

    async def _request_history_backfill(self, fund_codes: list[str]) -> None:
        """让队列为序列太薄的基金去补拉净值历史.

        这次读取保持不阻塞：任务由 broker 在请求之外执行，
        所以下一次打开列表时缺的那几列就补上了。
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
        """回溯一周 / 1、3、6、12 个月的区间收益，单位是百分点.

        analytics 里的辅助函数给出的是小数，而 `daily_return` 列存的已经是百分点；
        两者统一按这一列的单位输出，
        整行就能用同一个格式化函数处理（MVP spec 5.2）。
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
        """净值的抓取时间落在新鲜度窗口之内时返回 True."""
        if fetched_at is None:
            return False
        fetched_naive = fetched_at.replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
        return fetched_naive >= utc_now() - timedelta(days=_NAV_FRESH_DAYS)


watchlist_service = WatchlistService()
