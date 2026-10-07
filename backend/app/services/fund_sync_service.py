"""基金同步编排：由分布式锁保护、可幂等重跑的外部数据同步."""

import asyncio
from datetime import timedelta

from app.core.cache import cache_key, cache_service
from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import fund_sync_total
from app.core.task_queue import enqueue
from app.integrations.fund_data.akshare_client import AKSHARE_AVAILABLE
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.integrations.fund_data.models import FundExternalNav
from app.models.fund import Fund
from app.repositories.fund_repository import fund_repository, fund_write_repository
from app.repositories.job_repository import job_repository
from app.schemas.fund import FundNavRefreshResponse
from app.utils.clock import business_close_utc, business_today, utc_now
from app.workers import FUND_SYNC_TASK

# 批量行情表里没有某些基金的行（有的整家公司都不在这张表里），
# 这些只能退回逐只同步 —— 那条路径要三次上游调用，
# 因此每只基金每天最多只请求一次。
_MISSING_NAV_SYNC_COOLDOWN_SECONDS = 24 * 3600


def plan_nav_writes(
    codes: list[str], navs: list[FundExternalNav], funds: dict[str, Fund]
) -> tuple[list[FundExternalNav], list[str]]:
    """把批量行情的返回拆成"要写的行"和"要单独追的代码".

    有两类行绝不能写：调用方没要的代码（源表是全市场覆盖的），
    以及没有主数据行的代码 —— `fund_nav` 外键指向 `fund`，
    一条孤儿数据就会让整批分块 upsert 全部失败，
    连累同一批里其他本来能写进去的更新。
    这两类都归到 `missing`，交给逐只同步处理，那条路径会先把主数据行建出来。
    """
    wanted = set(codes)
    newest: dict[str, FundExternalNav] = {}
    for nav in navs:
        if nav.fund_code not in wanted:
            continue
        current = newest.get(nav.fund_code)
        if current is None or nav.nav_date > current.nav_date:
            newest[nav.fund_code] = nav
    writable = [nav for code, nav in sorted(newest.items()) if code in funds]
    missing = sorted(code for code in wanted if code not in newest or code not in funds)
    return writable, missing


class FundSyncService:
    """从外部数据源把单只或一批基金同步进 PostgreSQL.

    去重：用 ``fund_sync:{fund_code}:{date}`` 作键的分布式锁，
    避免两个 worker 在同一时刻同步同一只基金。锁在退出时就释放，
    所以它是互斥锁而不是"一天只放行一次"的闸门：
    主动重新同步一只基金，就会真的重新抓取一次。
    写入用 upsert，因此重试是幂等的 —— 重跑不会产生重复行。
    """

    async def sync_fund(self, fund_code: str, include_profile: bool = True) -> str:
        """同步单只基金的主数据与净值历史.

        Args:
            fund_code: 6 位基金代码。
            include_profile: 同时抓取基本信息档案。

        Returns:
            "written"（写入了新数据）、"skipped"（这个基金/日期的锁被另一个 worker 持有）
            或 "failed" 三者之一。
            worker 的任务流水需要区分它们：跳过不等于失败。
        """
        lock_key = f"fund_sync:{fund_code}:{business_today().isoformat()}"
        if not await cache_service.acquire_lock(lock_key, ttl=600):
            fund_sync_total.labels(status="skipped").inc()
            logger.debug("fund_sync_skipped_locked", fund_code=fund_code)
            return "skipped"

        try:
            written = False
            if include_profile:
                profile = await akshare_fund_provider.get_fund_profile(fund_code)
                if profile is not None:
                    await fund_write_repository.upsert_fund_from_record(profile)
                    written = True

            navs = await akshare_fund_provider.get_nav_history(fund_code)
            if navs:
                await fund_write_repository.upsert_navs(navs)
                written = True

            if written:
                # cache-aside：PostgreSQL 才是唯一可信源，
                # 热点缓存不能继续提供同步之前的净值（spec 7.14）。
                await cache_service.delete(cache_key("fund_latest_nav", fund_code))

            fund_sync_total.labels(status="written").inc()
            logger.info(
                "fund_sync_completed",
                fund_code=fund_code,
                nav_rows=len(navs),
                wrote=written,
            )
            return "written" if written else "skipped"
        except Exception as e:
            fund_sync_total.labels(status="failed").inc()
            logger.exception("fund_sync_failed", fund_code=fund_code, error=str(e))
            return "failed"
        finally:
            await cache_service.release_lock(lock_key)

    async def sync_funds_bounded(self, fund_codes: list[str], concurrency: int = 5) -> dict[str, int]:
        """以受限的并发量同步一批基金（MVP spec 7.7）.

        Args:
            fund_codes: 要同步的基金代码。
            concurrency: 同时进行的数据源调用上限。

        Returns:
            汇总字典：total / written / skipped / failed 各自的数量。
        """
        semaphore = asyncio.Semaphore(min(concurrency, 10))

        async def _bounded_sync(code: str) -> str:
            async with semaphore:
                return await self.sync_fund(code)

        results = await asyncio.gather(*[_bounded_sync(code) for code in fund_codes])
        summary = {
            "total": len(fund_codes),
            "written": sum(1 for status in results if status == "written"),
            "skipped": sum(1 for status in results if status == "skipped"),
            "failed": sum(1 for status in results if status == "failed"),
        }
        logger.info("fund_batch_sync_completed", **summary)
        return summary

    async def sync_hot_funds(self) -> dict[str, int]:
        """同步全部热门基金（被任何用户持有或加进自选的基金）."""
        codes = await fund_repository.get_hot_fund_codes()
        if not codes:
            logger.info("fund_hot_sync_no_targets")
            return {"total": 0, "written": 0, "skipped": 0, "failed": 0}
        return await self.sync_funds_bounded(codes)

    async def refresh_user_latest_navs(self, user_id: int) -> FundNavRefreshResponse:
        """刷新该用户持有或自选的全部基金的最新净值.

        一次批量源表就能回答整个集合，逐只路径每只要三次调用 ——
        正因为便宜，才可以在打开持仓页时跑。
        写入的行在接口返回之前已经落到 PostgreSQL，
        所以调用方可以立刻重新读列表。
        """
        codes = await fund_repository.list_user_fund_codes(user_id)
        if not codes:
            return FundNavRefreshResponse()
        if not AKSHARE_AVAILABLE:
            # 缺少该依赖时数据源会返回空列表，
            # 不在这里挡住就会被报成"所有基金都缺数据"。
            logger.warning("fund_nav_refresh_unavailable", user_id=user_id, count=len(codes))
            return FundNavRefreshResponse(requested=len(codes), status="unavailable")
        if not await cache_service.acquire_lock(
            cache_key("nav_refresh_user", str(user_id)), ttl=settings.FUND_NAV_REFRESH_COOLDOWN_SECONDS
        ):
            # 这是冷却时间而不是互斥锁：锁不释放，
            # 所以反复切换标签页的用户不会每聚焦一次就拉一次两万行的表。
            logger.debug("fund_nav_refresh_throttled", user_id=user_id, count=len(codes))
            return FundNavRefreshResponse(requested=len(codes), status="throttled")

        try:
            navs = await asyncio.wait_for(
                akshare_fund_provider.get_latest_navs(codes, force=True),
                timeout=settings.FUND_NAV_REFRESH_TIMEOUT_SECONDS,
            )
        except Exception as e:
            # 抓取仍在线程池里继续跑并填上源侧缓存，所以下一次尝试很便宜。
            # 页面上先留着旧的数字。
            logger.exception("fund_nav_refresh_failed", user_id=user_id, count=len(codes), error=str(e))
            return FundNavRefreshResponse(requested=len(codes), status="deferred")

        writable, missing = plan_nav_writes(codes, navs, await fund_repository.get_funds(codes))
        if writable:
            await fund_write_repository.upsert_navs(writable)
            for nav in writable:
                # 列表读的是 PostgreSQL，但详情页会缓存这个键：
                # 不删掉它就会继续给出刷新之前的净值。
                await cache_service.delete(cache_key("fund_latest_nav", nav.fund_code))
        for code in missing:
            await self._queue_missing_nav_refresh(code)

        logger.info(
            "fund_nav_refresh_completed",
            user_id=user_id,
            requested=len(codes),
            updated=len(writable),
            missing=len(missing),
        )
        return FundNavRefreshResponse(
            status="ok" if not missing else "partial",
            requested=len(codes),
            updated=len(writable),
            missing=missing,
            nav_date=max((nav.nav_date for nav in writable), default=None),
        )

    async def _queue_missing_nav_refresh(self, fund_code: str) -> None:
        """为批量表里没有的那只基金单独发起刷新.

        那张表里没有这只基金，不等于"没有要刷新的" ——
        有些基金根本不上这张表 —— 所以由逐只同步接手。
        因为那条路径要三次调用，每只基金每天只请求一次。
        """
        acquired = await cache_service.acquire_lock(
            cache_key("nav_refresh_missing", fund_code), ttl=_MISSING_NAV_SYNC_COOLDOWN_SECONDS
        )
        if not acquired:
            return
        try:
            await self.enqueue_sync(fund_code)
        except Exception as e:
            # 队列不可用只影响一只基金的数字，不影响整批刷新。
            logger.warning("fund_nav_refresh_fallback_failed", fund_code=fund_code, error=str(e))

    async def enqueue_sync(self, fund_code: str) -> str:
        """先记一笔任务，再把同步交给队列；不阻塞调用方.

        Args:
            fund_code: 要刷新的 6 位基金代码。

        Returns:
            任务流水的 id，调用方可以用它上报或追踪这次尝试。
        """
        job = await job_repository.create("FUND_SYNC", subject=fund_code)
        await enqueue(FUND_SYNC_TASK, fund_code=fund_code, job_id=job.id)
        logger.info("fund_sync_enqueued", fund_code=fund_code, job_id=job.id)
        return job.id

    async def is_nav_stale(self, fund_code: str) -> bool:
        """最新落库的净值超过陈旧容忍时长时返回 True."""
        latest = await fund_repository.get_latest_nav(fund_code)
        if latest is None:
            return True
        cutoff = utc_now() - timedelta(hours=settings.FUND_NAV_STALE_HOURS)
        # 没有 fetched_at 的行只带一个业务日期：这时跟当天 UTC 的收盘时刻比，
        # 而不是跟当地时间的零点比。
        fetched = latest.fetched_at or business_close_utc(latest.nav_date)
        return fetched < cutoff


fund_sync_service = FundSyncService()
