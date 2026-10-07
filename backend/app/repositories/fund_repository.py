"""基金数据仓储：基金主数据与净值历史的 PostgreSQL 落库.

读写都走 asyncpg 引擎（app.core.database）。写操作一律是短事务，事务之内绝不调用
外部数据源适配层（MVP spec 7.10）。
"""

from datetime import date

from sqlalchemy import func, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.database import get_async_session
from app.core.logging import logger
from app.integrations.fund_data.models import FundExternalNav, FundExternalProfile, FundExternalRecord
from app.models.fund import Fund, FundNav
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist
from app.utils.clock import utc_now

# asyncpg 单条语句最多 32767 个绑定参数；这里每行 8 列。
_UPSERT_CHUNK_ROWS = 2000


class FundRepository:
    """基金主数据与净值历史的异步数据访问."""

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    async def get_fund(self, fund_code: str) -> Fund | None:
        """按代码读取一条基金主数据."""
        async with get_async_session() as session:
            result = await session.execute(select(Fund).where(col(Fund.fund_code) == fund_code))
            return result.scalar_one_or_none()

    async def all_names(self) -> list[tuple[str, str]]:
        """把库里所有基金以 (代码, 名称) 返回，供名称匹配使用.

        只取两列：整张表要读进内存，给截图里识别出的名称打分，带上净值历史就装不下了。
        """
        async with get_async_session() as session:
            result = await session.execute(select(col(Fund.fund_code), col(Fund.fund_name)))
            return [(str(code), str(name)) for code, name in result.all()]

    async def search_funds(self, keyword: str, limit: int = 50) -> list[Fund]:
        """在本地基金主数据里按代码前缀或名称模糊搜索."""
        keyword_clean = keyword.strip()
        if not keyword_clean:
            return []
        pattern = f"%{keyword_clean}%"
        async with get_async_session() as session:
            statement = (
                select(Fund)
                .where(col(Fund.fund_code).ilike(pattern) | col(Fund.fund_name).ilike(pattern))
                .order_by(col(Fund.fund_code))
                .limit(limit)
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def nav_count(self, fund_code: str) -> int:
        """库里为这只基金存了多少个净值点."""
        async with get_async_session() as session:
            result = await session.execute(
                select(func.count()).select_from(FundNav).where(col(FundNav.fund_code) == fund_code)
            )
            return int(result.scalar_one())

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundNav]:
        """按日期升序读取净值行，起止日期可选."""
        async with get_async_session() as session:
            statement = select(FundNav).where(col(FundNav.fund_code) == fund_code)
            if start_date is not None:
                statement = statement.where(col(FundNav.nav_date) >= start_date)
            if end_date is not None:
                statement = statement.where(col(FundNav.nav_date) <= end_date)
            statement = statement.order_by(col(FundNav.nav_date))
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def get_latest_nav(self, fund_code: str) -> FundNav | None:
        """读取这只基金最新的一条净值行."""
        async with get_async_session() as session:
            statement = (
                select(FundNav)
                .where(col(FundNav.fund_code) == fund_code)
                .order_by(col(FundNav.nav_date).desc())
                .limit(1)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def get_nav_on_or_before(self, fund_code: str, on_or_before: date) -> FundNav | None:
        """读出这笔买入定价所依据的那个交易日.

        确认日不一定是发布净值的交易日（节假日确认的买入会往后滚），所以要的是它
        当天或之前最新的一行，而不是按精确日期去查。
        """
        async with get_async_session() as session:
            statement = (
                select(FundNav)
                .where(col(FundNav.fund_code) == fund_code, col(FundNav.nav_date) <= on_or_before)
                .order_by(col(FundNav.nav_date).desc())
                .limit(1)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def get_funds(self, fund_codes: list[str]) -> dict[str, Fund]:
        """按代码批量读取基金主数据行，结果以代码为键."""
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            result = await session.execute(select(Fund).where(col(Fund.fund_code).in_(fund_codes)))
            return {fund.fund_code: fund for fund in result.scalars().all()}

    async def get_latest_navs(self, fund_codes: list[str]) -> dict[str, FundNav]:
        """用一条 PostgreSQL DISTINCT ON 查出每只基金最新的那条净值行."""
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            statement = (
                select(FundNav)
                .where(col(FundNav.fund_code).in_(fund_codes))
                .distinct(col(FundNav.fund_code))
                .order_by(col(FundNav.fund_code), col(FundNav.nav_date).desc())
            )
            result = await session.execute(statement)
            return {row.fund_code: row for row in result.scalars().all()}

    async def get_nav_history_map(
        self, fund_codes: list[str], start_date: date | None = None
    ) -> dict[str, list[FundNav]]:
        """一次查询读出多只基金的净值序列，以代码为键.

        每只基金的列表都按日期升序，分析计算函数可以线性扫过去。没有净值行的基金
        不会出现在结果里。
        """
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            statement = select(FundNav).where(col(FundNav.fund_code).in_(fund_codes))
            if start_date is not None:
                statement = statement.where(col(FundNav.nav_date) >= start_date)
            statement = statement.order_by(col(FundNav.fund_code), col(FundNav.nav_date))
            result = await session.execute(statement)
            series: dict[str, list[FundNav]] = {}
            for row in result.scalars().all():
                series.setdefault(row.fund_code, []).append(row)
            return series

    async def get_hot_fund_codes(self) -> list[str]:
        """任何用户持有或自选过的去重基金代码（热门基金）."""
        position_codes = select(col(PortfolioPosition.fund_code)).distinct()
        watchlist_codes = select(col(Watchlist.fund_code)).distinct()
        async with get_async_session() as session:
            result = await session.execute(union_all(position_codes, watchlist_codes))
            return sorted({row[0] for row in result if row[0]})

    async def list_user_fund_codes(self, user_id: int) -> list[str]:
        """该用户持仓与自选的去重代码，也就是按需刷新的那批基金.

        持仓标记和自选标记喂的是同一批净值字段，一起刷新才能让持仓页看到口径
        一致的一组数字。
        """
        position_codes = (
            select(col(PortfolioPosition.fund_code)).where(col(PortfolioPosition.user_id) == user_id).distinct()
        )
        watchlist_codes = select(col(Watchlist.fund_code)).where(col(Watchlist.user_id) == user_id)
        async with get_async_session() as session:
            result = await session.execute(union_all(position_codes, watchlist_codes))
            return sorted({row[0] for row in result if row[0]})


class FundWriteRepository:
    """基金数据的写入侧操作（upsert）."""

    async def upsert_fund_from_record(self, record: FundExternalProfile | FundExternalRecord) -> None:
        """用一条外部记录插入或更新基金主数据行.

        搜索/榜单记录也带着最新净值，所以顺手把它写成一个 `fund_nav` 点 —— 否则
        只通过搜索见过的基金就没有 净值/涨跌 可列，而 spec 3.4 要求这两项都有值。
        """
        now = utc_now()
        values = {
            "fund_code": record.fund_code,
            "fund_name": record.fund_name,
            "source": "akshare",
            "fetched_at": now,
            "updated_at": now,
        }
        if isinstance(record, FundExternalProfile):
            values.update(
                {
                    "fund_type": record.fund_type,
                    "company": record.company,
                    "manager_name": record.manager_name,
                    "inception_date": record.inception_date,
                    "asset_size": record.asset_size,
                }
            )
        # 搜索记录带着已公布的净值日期，这一行说的就是截至那一天的数据
        as_of = getattr(record, "nav_date", None)
        if as_of is not None:
            values["source_as_of"] = as_of
        async with get_async_session() as session:
            statement = pg_insert(Fund).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[Fund.fund_code],
                set_={key: value for key, value in values.items() if key != "fund_code"},
            )
            await session.execute(statement)

        if isinstance(record, FundExternalRecord) and record.nav_date is not None:
            await self.upsert_navs(
                [
                    FundExternalNav(
                        fund_code=record.fund_code,
                        nav_date=record.nav_date,
                        unit_nav=record.latest_nav,
                        accumulated_nav=record.latest_accumulated,
                        daily_return=record.daily_return,
                    )
                ]
            )

    async def upsert_navs(self, navs: list[FundExternalNav]) -> int:
        """分片批量 upsert 净值行，返回写入的行数.

        每条语句每行要占 8 个绑定参数，而 asyncpg 的上限是 32767，所以老基金的
        完整历史必须切片，否则它的同步会一直失败。
        """
        if not navs:
            return 0
        now = utc_now()
        written = 0
        async with get_async_session() as session:
            for offset in range(0, len(navs), _UPSERT_CHUNK_ROWS):
                chunk = navs[offset : offset + _UPSERT_CHUNK_ROWS]
                rows = [
                    {
                        "fund_code": nav.fund_code,
                        "nav_date": nav.nav_date,
                        "unit_nav": nav.unit_nav,
                        "accumulated_nav": nav.accumulated_nav,
                        "daily_return": nav.daily_return,
                        "source": "akshare",
                        "fetched_at": now,
                    }
                    for nav in chunk
                ]
                statement = pg_insert(FundNav).values(rows)
                statement = statement.on_conflict_do_update(
                    constraint="uq_fund_nav_code_date",
                    set_={
                        # 载荷里是 NULL，只说明上游没给这个数，不代表库里存的值错了。
                        # 批量行情表并不给每只基金都带 累计净值，这里无条件覆盖会把
                        # 详情页要展示的数字抹成空。
                        "unit_nav": func.coalesce(statement.excluded.unit_nav, FundNav.unit_nav),
                        "accumulated_nav": func.coalesce(statement.excluded.accumulated_nav, FundNav.accumulated_nav),
                        "daily_return": func.coalesce(statement.excluded.daily_return, FundNav.daily_return),
                        "source": statement.excluded.source,
                        "fetched_at": statement.excluded.fetched_at,
                    },
                )
                await session.execute(statement)
                written += len(rows)
        logger.debug("fund_navs_upserted", fund_code=navs[0].fund_code, rows=written)
        return written


fund_repository = FundRepository()
fund_write_repository = FundWriteRepository()
