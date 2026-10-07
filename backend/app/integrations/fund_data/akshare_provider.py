"""基于 AKShare 的 FundDataProvider，用有界并发做隔离.

AKShare 的调用是同步阻塞的，这里把每次调用放到 worker 线程里跑，前面套四道闸
门：信号量（有界并发）、最小间隔限速、单次调用超时、tenacity 重试
（MVP spec 7.6）。配置只从环境变量来.
"""

import asyncio
import functools
import logging
import time
from datetime import date
from typing import Any

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger
from app.integrations.fund_data.akshare_client import AKSHARE_AVAILABLE, ak
from app.integrations.fund_data.models import (
    FundExternalHolding,
    FundExternalIndustry,
    FundExternalManager,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
    IndexExternalQuote,
    StockExternalQuote,
)
from app.integrations.fund_data.normalizer import (
    normalize_fund_record,
    normalize_holding_rows,
    normalize_index_rows,
    normalize_industry_rows,
    normalize_nav_rows,
    normalize_profile_rows,
    parse_quarter,
    sina_symbol,
)
from app.integrations.fund_data.sina_client import fetch_quotes
from app.utils.clock import business_today
from app.utils.sanitization import sanitize_string

# 把整张开放式基金排行表缓存在进程里，搜索和取最新净值都很便宜。
_RANK_CACHE_TTL_SECONDS = 6 * 3600
# 强制重建（按需刷新报价）会无视上面的 TTL；但这张表一天只公布一次，
# 一分钟内刷两次没有任何收益。
_RANK_MIN_REFRESH_SECONDS = 60
# 代码与名称主数据表一个月才变几次；按天刷新，就能保证截图识别导入
# 一天最多只为它付一次代价。
_NAME_DIRECTORY_TTL_SECONDS = 24 * 3600


def match_records(records: list[FundExternalRecord], keyword: str) -> list[FundExternalRecord]:
    """按代码或名称做子串匹配.

    AKShare 的排行接口一次返回整张表，没有查询参数，所以模糊搜索只能在这里做。
    中文名称按子串匹配，正合用户的输入习惯——搜 "华泰柏瑞" 就能命中
    "华泰柏瑞质量成长混合C".
    """
    lowered = keyword.lower()
    return [record for record in records if lowered in record.fund_code or lowered in record.fund_name.lower()]


class AKShareFundProvider:
    """包住 AKShare 同步基金接口的有界并发适配器."""

    def __init__(self) -> None:
        """初始化有界并发原语和各份缓存."""
        self._semaphore = asyncio.Semaphore(settings.AKSHARE_MAX_CONCURRENCY)
        self._throttle_lock = asyncio.Lock()
        self._last_call_monotonic = 0.0
        self._rank_index: list[FundExternalRecord] = []
        self._rank_cached_at = 0.0
        self._rank_attempted_at = 0.0
        self._rank_lock = asyncio.Lock()
        self._name_directory: list[tuple[str, str]] = []
        self._name_cached_at = 0.0

    # ------------------------------------------------------------------
    # 对外接口（FundDataProvider）
    # ------------------------------------------------------------------

    async def search_funds(self, keyword: str) -> list[FundExternalRecord]:
        """在排行表里按代码子串或模糊名称搜基金."""
        keyword_clean = sanitize_string(keyword).strip()
        if not keyword_clean:
            return []
        index = await self._get_rank_index()
        return match_records(index, keyword_clean)[:50]

    async def get_fund_profile(self, fund_code: str) -> FundExternalProfile | None:
        """从单只基金的基本信息接口取主数据."""
        rows = await self._call("fund_individual_basic_info_xq", symbol=fund_code)
        return normalize_profile_rows(rows, fund_code)

    async def get_latest_nav(self, fund_code: str) -> FundExternalNav | None:
        """取最近一天的净值：先查排行表，没有再走历史净值."""
        index = await self._get_rank_index()
        for record in index:
            # 没有净值日期的行直接跳过，不能替它补成"今天"：编造日期会把
            # fund_nav 这点写到可能根本不是交易日的某一天，后面每个区间计算
            # 都会以这个假日期为锚。
            if record.fund_code == fund_code and record.nav_date is not None:
                return FundExternalNav(
                    fund_code=fund_code,
                    nav_date=record.nav_date,
                    unit_nav=record.latest_nav,
                    accumulated_nav=record.latest_accumulated,
                    daily_return=record.daily_return,
                )
        history = await self.get_nav_history(fund_code)
        return history[0] if history else None

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundExternalNav]:
        """拉取单位净值与累计净值，再合并成历史序列."""
        unit_rows = await self._call("fund_open_fund_info_em", symbol=fund_code, indicator="单位净值走势")
        accumulated_rows: list[dict[str, Any]] = []
        try:
            accumulated_rows = await self._call("fund_open_fund_info_em", symbol=fund_code, indicator="累计净值走势")
        except Exception as e:
            logger.warning("fund_accumulated_nav_unavailable", fund_code=fund_code, error=str(e))

        navs = normalize_nav_rows(unit_rows or [], accumulated_rows, fund_code)
        if end_date is not None:
            navs = [nav for nav in navs if nav.nav_date <= end_date]
        if start_date is not None:
            navs = [nav for nav in navs if nav.nav_date >= start_date]
        return navs

    async def get_latest_navs(self, fund_codes: list[str], force: bool = False) -> list[FundExternalNav]:
        """从排行表一次读多只基金的最新净值.

        上游一次调用就能覆盖任意多个代码，所以按需刷新报价是批量做的，
        而不是一只基金一只基金地同步.
        """
        if not fund_codes:
            return []
        wanted = set(fund_codes)
        index = await self._get_rank_index(force)
        return [
            FundExternalNav(
                fund_code=record.fund_code,
                nav_date=record.nav_date,
                unit_nav=record.latest_nav,
                accumulated_nav=record.latest_accumulated,
                daily_return=record.daily_return,
            )
            for record in index
            if record.fund_code in wanted and record.latest_nav is not None and record.nav_date is not None
        ]

    async def get_fund_manager(self, fund_code: str) -> FundExternalManager | None:
        """从基本信息接口取现任基金经理."""
        profile = await self.get_fund_profile(fund_code)
        if profile is None:
            return None
        return FundExternalManager(fund_code=fund_code, manager_name=profile.manager_name)

    async def get_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        """取最近两个报告期披露的股票持仓.

        界面要显示的季度环比离不开上一期披露，而这个接口是按年取数的，
        所以只有当年只公布了一个季度时才去拉上一年.
        """
        year = business_today().year
        rows: list[dict[str, Any]] = []
        for candidate in (year, year - 1):
            rows.extend(await self._call("fund_portfolio_hold_em", symbol=fund_code, date=str(candidate)))
            quarters = {parse_quarter(row.get("季度")) for row in rows}
            if len(quarters - {None}) >= 2:
                break
        return normalize_holding_rows(rows, fund_code)

    async def get_stock_quotes(self, stock_codes: list[str]) -> list[StockExternalQuote]:
        """一次批量请求，给持仓股票跨 A股/港股/美股取行情."""
        symbols = [symbol for symbol in (sina_symbol(code) for code in stock_codes) if symbol]
        if not symbols:
            return []
        try:
            return await fetch_quotes(symbols)
        except Exception as e:
            # 行情源挂掉只损失一列数据，不该拖垮整个持仓页。
            logger.warning("stock_quotes_unavailable", count=len(symbols), error=str(e))
            return []

    async def get_industry_allocation(self, fund_code: str) -> list[FundExternalIndustry]:
        """取最新一次披露的行业权重.

        基金在所查年份里没有披露（成立晚于该年）时接口会抛异常，所以每个候选
        年份各自试一次，不让一次落空把整个查询判成失败.
        """
        year = business_today().year
        for candidate in (year, year - 1):
            try:
                rows = await self._call("fund_portfolio_industry_allocation_em", symbol=fund_code, date=str(candidate))
            except Exception as e:
                logger.debug("fund_industry_year_unavailable", fund_code=fund_code, year=candidate, error=str(e))
                continue
            industries = normalize_industry_rows(rows or [], fund_code)
            if industries:
                return industries
        return []

    async def get_index_history(
        self,
        index_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[IndexExternalQuote]:
        """取业绩比较基准指数的日线收盘价，用于画对比线.

        这不在 FundDataProvider 协议里：指数不是基金事实，它只是复用这个适配器
        受保护的传输（限速、信号量、超时、重试）。新浪接口一次就返回全部历史，
        所以区间过滤在这里做；东财的指数接口在某些网络下连不通.
        """
        rows = await self._call("stock_zh_index_daily", symbol=index_code)
        quotes = normalize_index_rows(rows or [], index_code)
        if start_date is not None:
            quotes = [quote for quote in quotes if quote.trade_date >= start_date]
        if end_date is not None:
            quotes = [quote for quote in quotes if quote.trade_date <= end_date]
        return quotes

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _get_rank_index(self, force: bool = False) -> list[FundExternalRecord]:
        """返回归一化后的开放式基金排行表，带进程内缓存.

        归一化每次刷新只做一遍：原始行的列名是中文，拿英文键去匹配会静默地
        永远命中不了.
        """
        if self._rank_is_reusable(force):
            return self._rank_index
        async with self._rank_lock:
            # 抢锁输了的一方仍然要再判一次：排队这段时间里可能已经有人把表建好，
            # 这次请求也就已经有答案了。
            if self._rank_is_reusable(force):
                return self._rank_index
            self._rank_attempted_at = time.monotonic()
            rows = await self._call("fund_open_fund_rank_em", symbol="全部")
            normalized = [item for row in rows or [] if (item := normalize_fund_record(row)) is not None]
            if normalized:
                self._rank_index = normalized
                self._rank_cached_at = time.monotonic()
                logger.info("akshare_rank_index_built", rows=len(normalized), forced=force)
            return normalized

    def _rank_is_reusable(self, force: bool) -> bool:
        """进程内这张表能不能直接回答本次读取，不用再拉上游.

        防击穿的标记是在发起调用之前就打的，所以上游挂掉时每分钟只浪费一次尝试，
        而不是页面每聚焦一次就再试一遍.
        """
        if not self._rank_index:
            return False
        if force:
            return (time.monotonic() - self._rank_attempted_at) < _RANK_MIN_REFRESH_SECONDS
        return (time.monotonic() - self._rank_cached_at) < _RANK_CACHE_TTL_SECONDS

    async def get_name_directory(self) -> list[tuple[str, str]]:
        """全部在册基金的代码与名称对照表，带缓存.

        排行表会整家公司都缺——比如根本没有广发纳指那一行——所以截图识别出来的
        名称要匹配，得靠这份主数据表。它变化很慢、一次调用就能拿全，
        因此缓存时间放得更长.
        """
        if self._name_directory and (time.monotonic() - self._name_cached_at) < _NAME_DIRECTORY_TTL_SECONDS:
            return self._name_directory
        rows = await self._call("fund_name_em")
        directory = [
            (str(row["基金代码"]).strip(), str(row["基金简称"]).strip())
            for row in rows or []
            if row.get("基金代码") and row.get("基金简称")
        ]
        if directory:
            self._name_directory = directory
            self._name_cached_at = time.monotonic()
            logger.info("akshare_name_directory_built", rows=len(directory))
        return directory

    async def _throttle(self) -> None:
        """强制两次外部调用之间留足最小间隔."""
        async with self._throttle_lock:
            elapsed = time.monotonic() - self._last_call_monotonic
            wait = settings.AKSHARE_MIN_INTERVAL_SECONDS - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_monotonic = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call(self, func_name: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """在限速、信号量和超时的保护下，用一个线程跑一个 AKShare 函数."""
        if not AKSHARE_AVAILABLE or ak is None:
            logger.warning("akshare_not_available", func_name=func_name)
            return []

        # 名额要等 worker 线程的完成回调归还，不能在本协程恢复时就还。
        # 线程一旦启动就取消不掉，超时就放行等于把名额提前放掉：
        # 每卡住一次调用，实际并发就往上多挪一个，逐次累积下去，
        # 最终会突破 AKSHARE_MAX_CONCURRENCY 的上限。
        await self._semaphore.acquire()
        try:
            # run_in_executor 只转发位置参数：这里用到的 AKShare 函数都是关键字
            # 参数（symbol、indicator）方式调的，必须先把它们绑好，否则 executor
            # 会拒收。
            future = asyncio.get_running_loop().run_in_executor(
                None, functools.partial(self._call_sync, func_name, *args, **kwargs)
            )
        except Exception:
            self._semaphore.release()
            raise
        future.add_done_callback(lambda _future: self._semaphore.release())

        try:
            await self._throttle()
            records = await asyncio.wait_for(future, timeout=settings.AKSHARE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "akshare_call_timeout",
                func_name=func_name,
                timeout_seconds=settings.AKSHARE_TIMEOUT_SECONDS,
            )
            raise TimeoutError(f"akshare call {func_name} timed out")
        except Exception as e:
            logger.warning("akshare_call_failed", func_name=func_name, error=str(e))
            raise
        logger.debug("akshare_call_successful", func_name=func_name, rows=len(records))
        return records

    def _call_sync(self, func_name: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """阻塞式 AKShare 调用——只在 worker 线程里跑."""
        func = getattr(ak, func_name, None)
        if func is None:
            raise ValueError(f"akshare function not found: {func_name}")
        frame = func(*args, **kwargs)
        return frame.to_dict("records")


akshare_fund_provider = AKShareFundProvider()
