"""自选仓储：自选条目、自选分组与分组关联."""

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.database import get_async_session
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist, WatchlistGroup, WatchlistGroupItem
from app.utils.clock import utc_now


class WatchlistRepository:
    """用户自选及其分组的异步数据访问."""

    # ------------------------------------------------------------------
    # 自选条目
    # ------------------------------------------------------------------

    async def list_funds(self, user_id: int) -> list[Watchlist]:
        """按 sort_order 列出该用户的自选基金."""
        async with get_async_session() as session:
            statement = (
                select(Watchlist)
                .where(col(Watchlist.user_id) == user_id)
                .order_by(col(Watchlist.sort_order), col(Watchlist.id))
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def add_fund(self, user_id: int, fund_code: str) -> Watchlist:
        """把基金加入自选，重复添加也不会出错.

        这里靠 INSERT ... 在 ON CONFLICT 时 DO NOTHING：先前查再插的写法，会让两个
        并发的首次添加都看到没有记录，输掉的那个把唯一约束冲突暴露成 500。
        """
        async with get_async_session() as session:
            statement = pg_insert(Watchlist).values(
                user_id=user_id,
                fund_code=fund_code,
                sort_order=0,
                created_at=utc_now(),
            )
            await session.execute(statement.on_conflict_do_nothing(constraint="uq_watchlist_user_fund"))
            result = await session.execute(
                select(Watchlist).where(col(Watchlist.user_id) == user_id, col(Watchlist.fund_code) == fund_code)
            )
            return result.scalar_one()

    async def remove_fund(self, user_id: int, fund_code: str) -> bool:
        """移除自选（连同它的分组归属），删掉了才返回 True."""
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
        """更新某只基金在自选列表里的排序位置."""
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
        """该用户是否把这只基金加入了自选."""
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
        """该用户是否在某个账户里持有这只基金."""
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
        """一次批量查出该用户在任意账户里持有的基金代码."""
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
    # 分组
    # ------------------------------------------------------------------

    async def list_groups(self, user_id: int) -> list[WatchlistGroup]:
        """按 sort_order 列出该用户的自选分组."""
        async with get_async_session() as session:
            result = await session.execute(
                select(WatchlistGroup)
                .where(col(WatchlistGroup.user_id) == user_id)
                .order_by(col(WatchlistGroup.sort_order), col(WatchlistGroup.id))
            )
            return list(result.scalars().all())

    async def get_group(self, user_id: int, group_id: int) -> WatchlistGroup | None:
        """读取属于该用户的一个分组."""
        async with get_async_session() as session:
            result = await session.execute(
                select(WatchlistGroup).where(
                    col(WatchlistGroup.id) == group_id, col(WatchlistGroup.user_id) == user_id
                )
            )
            return result.scalar_one_or_none()

    async def create_group(self, user_id: int, name: str, sort_order: int = 0) -> WatchlistGroup:
        """新建一个自定义自选分组."""
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
        """分组改名或调整顺序."""
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
        """删除分组，以及它与自选条目的关联."""
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
        """把已自选的基金放进某个分组（重复添加不报错）."""
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
        """为每只自选基金给出 基金代码 → [(group_id, group_name)] 的映射.

        用一次 join 查完，而不是一行一次查询，并且保住用户自己设定的分组顺序
        （组内次序记在 ``watchlist_group_item.sort_order`` 里）。
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
        """重写一个分组的成员和组内顺序（spec 3.3 排序）.

        Args:
            user_id: 归属用户 id —— 分组必须属于调用方。
            group_id: 要重写的分组。
            fund_codes: 期望的成员，按展示顺序给出；用户没加入自选的代码会被忽略。

        Returns:
            更新成功返回 True，有代码不在自选里返回 False，分组不存在返回 None。
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
        """重写某只自选基金所属的那几组.

        Returns:
            基金确实在自选里返回 True（哪怕分组一个都没变），自选条目不存在返回 False。
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
