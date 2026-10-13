"""基金域服务：搜索、详情、净值历史、业绩、基金解析.

基金相关的事实一律由 FundService 给出 —— 其他服务、API 层以及后续的 Agent 工具
都不直接碰基金数据源适配层（spec 14.1）。
线上读取优先走 PostgreSQL，Redis 只做热点缓存；只有本地数据缺失或过期时，
才把外部同步入队或内联执行（spec 5.6）。
"""

import asyncio
import json
import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlmodel import col

from app.analytics import annualized_volatility, disclosed_change, max_drawdown, period_return, range_return
from app.analytics.returns import NavPoint
from app.core.cache import cache_key, cache_service
from app.core.config import settings
from app.core.database import get_async_session
from app.core.logging import logger
from app.integrations.fund_data.akshare_client import AKSHARE_AVAILABLE
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.integrations.fund_data.models import FundExternalHolding, FundExternalRecord
from app.integrations.fund_data.normalizer import parse_quarter, sina_symbol, tencent_symbol
from app.integrations.holdings.name_match import NameMatch, decide, rank_names
from app.models.fund import Fund, FundNav
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist
from app.repositories.fund_repository import fund_repository, fund_write_repository
from app.schemas.fund import (
    FundDetailResponse,
    FundHoldingItem,
    FundHoldingsResponse,
    FundIndustryItem,
    FundNavHistoryResponse,
    FundNavPoint,
    FundPerformance,
    FundSearchItem,
    NavRange,
)
from app.schemas.sector import FundSectorEvidence
from app.schemas.fund_selection import FundSelectionOption
from app.schemas.fund_disclosure import (
    FundAnnouncementPage,
    FundAnnouncementsRequest,
    FundAnnouncementsResult,
    FundManagerHistoryData,
    FundManagersResult,
)
from app.services.fund_disclosure_utils import cached_disclosure, merge_manager_tenures
from app.services.fund_sync_service import fund_sync_service
from app.utils.clock import business_today, range_start

_LATEST_NAV_CACHE_TTL_SECONDS = 300
_SEARCH_CACHE_TTL_SECONDS = 300
# 持仓披露一个季度才变一次，所以即使压在它上面的行情不缓存，
# 这次披露数据的抓取本身也要缓存。
_HOLDINGS_CACHE_TTL_SECONDS = 3600
_TOP_HOLDINGS = 10
# 走势图需要两个点；搜索结果和榜单只会留下一条最新净值，
# 所以少于这个点数就算"从来没真正同步过"。
_MIN_HISTORY_POINTS = 2
# 对"内联补过历史之后仍然显得很薄"的基金，要退避这么久才再试一次 ——
# 真正新发的基金本来就只有一个净值点。
_FULL_SYNC_RETRY_TTL_SECONDS = 86400


def _weight_change(weight: float | None, previous: float | None) -> float | None:
    """单只重仓股的 占净值比例 相对上一季度的变动，单位是百分点."""
    if weight is None or previous is None:
        return None
    return round(weight - previous, 4)


def summarize_holdings(
    holdings: list[FundExternalHolding],
) -> tuple[str | None, str | None, list[FundHoldingItem]]:
    """取最近一次披露的季度，并把每一行和上一季度的对应行做比较.

    Returns:
        最新季度的标签、上一季度的标签，以及按权重排好序的重仓股。
        季度解析不出来的行（上游在不同版本里改过这一列的名字）直接丢弃，
        不去猜它属于哪个季度。
    """
    by_quarter: dict[tuple[int, int], list[FundExternalHolding]] = {}
    for holding in holdings:
        key = parse_quarter(holding.quarter)
        if key is not None:
            by_quarter.setdefault(key, []).append(holding)
    if not by_quarter:
        return None, None, []

    ordered = sorted(by_quarter)
    latest_key = ordered[-1]
    previous_key = ordered[-2] if len(ordered) > 1 else None
    previous_weights = (
        {holding.stock_code: holding.weight for holding in by_quarter[previous_key]} if previous_key else {}
    )

    items = [
        FundHoldingItem(
            stock_code=holding.stock_code,
            symbol=tencent_symbol(holding.stock_code),
            stock_name=holding.stock_name,
            weight=holding.weight,
            weight_change=_weight_change(holding.weight, previous_weights.get(holding.stock_code)),
            # 上一次披露里没有这个代码，说明是新进的仓位，不是数据缺口；
            # 根本没有更早的季度时，什么都证明不了。
            is_new=previous_key is not None and holding.stock_code not in previous_weights,
        )
        for holding in by_quarter[latest_key]
    ]
    items.sort(key=lambda item: item.weight if item.weight is not None else -1.0, reverse=True)

    def label(key: tuple[int, int]) -> str:
        return f"{key[0]}年{key[1]}季度"

    return (
        label(latest_key),
        label(previous_key) if previous_key else None,
        items[:_TOP_HOLDINGS],
    )


class FundService:
    """供 API、导入流程和后续 Agent 工具共用的异步基金数据服务."""

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    async def search_analysis_candidates(self, keyword: str) -> list[FundSelectionOption]:
        """在完整名称目录中模糊匹配，按相似度去重后返回前三只基金.

        名称目录同时保留登记名与展示简称，不依赖连续子串、个人持仓或排行覆盖。
        此步骤只解析标识，不抓取候选净值或提前同步所有候选的历史。
        """
        cleaned = keyword.strip()
        if not cleaned:
            return []
        if re.fullmatch(r"[0-9]{6}", cleaned):
            funds = await self._search_fund_rows(cleaned)
            return [
                FundSelectionOption(
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    fund_type=fund.fund_type,
                )
                for fund in funds
                if fund.fund_code == cleaned
            ][:1]
        return await self._match_fund_names(cleaned)

    async def _match_fund_names(self, keyword: str) -> list[FundSelectionOption]:
        """普通搜索和分析选择共用的名称匹配规则，先去重再取相似度 Top3."""
        directory = await self.name_directory()
        valid = [(code, name) for code, name in directory if re.fullmatch(r"[0-9]{6}", code) and name.strip()]
        # 同一代码的长短别名可能占掉三个名额，必须先完整打分，再按代码取前三。
        ranked = rank_names(keyword, valid, limit=len(valid), min_score=0.5)

        def exact(name: str) -> bool:
            return "".join(name.split()).casefold() == "".join(keyword.split()).casefold()

        ranked.sort(
            key=lambda match: (not exact(match.fund_name), -match.score, len(match.fund_name), match.fund_code)
        )
        candidates: dict[str, FundSelectionOption] = {}
        for match in ranked:
            candidates.setdefault(
                match.fund_code, FundSelectionOption(fund_code=match.fund_code, fund_name=match.fund_name)
            )
            if len(candidates) == 3:
                break
        return list(candidates.values())

    async def search(self, keyword: str, user_id: int) -> list[FundSearchItem]:
        """搜索基金：先按代码/名称子串搜索，无名称结果时复用分析候选的模糊匹配.

        Args:
            keyword: 代码、全称、简称或模糊片段。
            user_id: 调用方 id，用于给出 is_watchlisted / is_held 标记。

        Returns:
            最多 50 条搜索结果。
        """
        keyword_clean = keyword.strip()
        if not keyword_clean:
            return []

        funds = await self._search_fund_rows(keyword_clean)
        if not funds:
            return []

        codes = [fund.fund_code for fund in funds]
        navs = await fund_repository.get_latest_navs(codes)
        missing = [code for code in codes if code not in navs]
        if missing:
            navs = await self._backfill_navs(missing, codes)
        watchlisted, held = await self._user_flag_sets(user_id)
        return [
            FundSearchItem(
                fund_code=fund.fund_code,
                fund_name=fund.fund_name,
                fund_type=fund.fund_type,
                latest_nav=nav.unit_nav if nav else None,
                nav_date=nav.nav_date if nav else None,
                daily_return=nav.daily_return if nav else None,
                is_watchlisted=fund.fund_code in watchlisted,
                is_held=fund.fund_code in held,
            )
            for fund in funds
            for nav in [navs.get(fund.fund_code)]
        ]

    async def _backfill_navs(self, missing: list[str], codes: list[str]) -> dict[str, FundNav]:
        """给没有净值的搜索结果补写净值，然后重新读一次 PostgreSQL.

        基金在净值落库之前就被搜到（或者是被别的用户同步进来的），
        否则它的 净值/涨跌 会显示成 `--`，而 spec 3.4 要求这两项必须有值。
        读取仍然只来自 PostgreSQL，数据源只负责把缺口填上。
        """
        if AKSHARE_AVAILABLE:
            try:
                external = await akshare_fund_provider.get_latest_navs(missing)
                if external:
                    await fund_write_repository.upsert_navs(external)
            except Exception as e:
                logger.warning("fund_nav_backfill_failed", count=len(missing), error=str(e))
        return await fund_repository.get_latest_navs(codes)

    async def _search_fund_rows(self, keyword_clean: str) -> list[Fund]:
        """读出匹配的基金主数据行，并缓存这份共享的结果集.

        缓存里只放公开数据，每个用户的标记不参与缓存键，
        所以某个用户改了自己的自选，绝不会被别人的缓存条目盖住 ——
        也不会被自己的盖住，因为标记是实时读取的。
        """
        cached = await cache_service.get(cache_key("fund_search", keyword_clean))
        if cached:
            return self._decode_funds(cached)

        local_funds = await fund_repository.search_funds(keyword_clean)
        if not local_funds and AKSHARE_AVAILABLE:
            try:
                external = await akshare_fund_provider.search_funds(keyword_clean)
            except Exception as e:
                # 数据源挂了就按空结果页处理，而不是 500：
                # 本地表里有匹配项时，调用方照样看得到它们。
                logger.warning("fund_external_search_failed", keyword=keyword_clean, error=str(e))
                external = []
            for record in external[:50]:
                await fund_write_repository.upsert_fund_from_record(record)
            local_funds = await fund_repository.search_funds(keyword_clean)
            # 6 位代码在榜单表里查不到时（场内基金、新发的基金），
            # 仍然可以直接抓取这一只基金来解析。
            if not local_funds and len(keyword_clean) == 6 and keyword_clean.isdigit():
                await fund_sync_service.sync_fund(keyword_clean)
                local_funds = await fund_repository.search_funds(keyword_clean)

        if not local_funds and not keyword_clean.isdigit():
            local_funds = await self._fuzzy_search_fund_rows(keyword_clean)

        funds = local_funds[:50]
        if funds:
            await cache_service.set(
                cache_key("fund_search", keyword_clean),
                self._encode_funds(funds),
                ttl=_SEARCH_CACHE_TTL_SECONDS,
            )
        return funds

    async def _fuzzy_search_fund_rows(self, keyword: str) -> list[Fund]:
        """复用完整名册的 Top3 匹配，再按候选代码读取主数据，保留相似度顺序."""
        try:
            candidates = await self._match_fund_names(keyword)
        except Exception:
            logger.exception("fund_fuzzy_search_failed", keyword=keyword)
            return []
        if not candidates:
            return []

        codes = [candidate.fund_code for candidate in candidates]
        known = await fund_repository.get_funds(codes)
        missing = [candidate for candidate in candidates if candidate.fund_code not in known]
        # 简称只用于新基金的首次登记，不能覆盖数据库中已有的正式名称和资料。
        for candidate in missing:
            await fund_write_repository.upsert_fund_from_record(
                FundExternalRecord(
                    fund_code=candidate.fund_code,
                    fund_name=candidate.fund_name,
                    fund_type=candidate.fund_type,
                )
            )
        if missing:
            known = await fund_repository.get_funds(codes)
        # 模糊候选不能再按原始子串过滤，否则名称中缺少的词会让结果再次变空。
        return [known[code] for code in codes if code in known]

    # ------------------------------------------------------------------
    # 详情 / 净值 / 业绩
    # ------------------------------------------------------------------

    async def get_detail(self, fund_code: str, user_id: int) -> FundDetailResponse | None:
        """返回基金概况；第一次见到某只基金时把数据同步下来."""
        await self.ensure_fund_data(fund_code)
        fund = await fund_repository.get_fund(fund_code)
        if fund is None:
            return None

        latest = await self._latest_nav_cached(fund_code)
        history = await fund_repository.get_nav_history(fund_code)
        points = self._to_points(history)
        is_watchlisted, is_held = await self._user_flags(fund_code, user_id)

        end = latest.nav_date if latest else business_today()
        # 与两张列表同一口径：披露 0.00% 而净值步进对不上，那是"那天没有行情"
        # （QDII 的境外休市日），不是"今天没涨没跌"。
        previous = (
            history[-2].unit_nav
            if latest is not None and len(history) >= 2 and history[-1].nav_date == latest.nav_date
            else None
        )
        return FundDetailResponse(
            fund_code=fund.fund_code,
            fund_name=fund.fund_name,
            fund_type=fund.fund_type,
            company=fund.company,
            manager_name=fund.manager_name,
            inception_date=fund.inception_date,
            asset_size=fund.asset_size,
            latest_nav=latest.unit_nav if latest else None,
            accumulated_nav=latest.accumulated_nav if latest else None,
            nav_date=latest.nav_date if latest else None,
            daily_return=disclosed_change(previous, latest.unit_nav, latest.daily_return) if latest else None,
            performance=self._compute_performance(points, end),
            is_watchlisted=is_watchlisted,
            is_held=is_held,
            source=fund.source,
            # AKShare 的榜单表没有"数据截至"这一列；我们手上最新的净值日期，
            # 才是"这份数据描述的是什么时候"的诚实答案。
            source_as_of=fund.source_as_of or (latest.nav_date if latest else None),
            updated_at=fund.updated_at or fund.fetched_at,
            nav_fetched_at=latest.fetched_at if latest else None,
        )

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        range_key: NavRange | None = None,
        limit: int | None = None,
        before_date: date | None = None,
    ) -> FundNavHistoryResponse:
        """返回已落库的净值序列，供画图使用（不实时穿透到外部数据源）.

        Args:
            fund_code: 6 位基金代码。
            start_date: 显式的下界；给了 `range_key` 时以它为准。
            end_date: 显式的上界。
            range_key: spec 3.5.3 里的命名区间（1m/3m/6m/1y/3y/all）。
            limit: 只保留最新的 N 个点，用于历史列表翻页。
            before_date: 排他游标 —— 只取严格早于这一天的点，
                客户端因此能往回翻页而不重复上一页。
        """
        await self.ensure_fund_data(fund_code)
        if range_key is not None:
            start_date = range_start(range_key, business_today())
        if before_date is not None:
            cursor_end = before_date - timedelta(days=1)
            end_date = min(end_date, cursor_end) if end_date else cursor_end
        history = await fund_repository.get_nav_history(fund_code, start_date, end_date)
        page, has_more = _newest_page(history, limit)
        return FundNavHistoryResponse(
            fund_code=fund_code,
            range=range_key,
            total=len(history),
            has_more=has_more,
            points=[
                FundNavPoint(
                    nav_date=row.nav_date,
                    unit_nav=row.unit_nav,
                    accumulated_nav=row.accumulated_nav,
                    daily_return=row.daily_return,
                )
                for row in page
            ],
        )

    async def get_sector_evidence(self, fund_code: str) -> FundSectorEvidence | None:
        """只取得名称与披露行业，不为板块识别抓历史净值或重仓股实时行情."""
        fund = await fund_repository.get_fund(fund_code)
        if fund is None:
            profile = await akshare_fund_provider.get_fund_profile(fund_code)
            if profile is None:
                return None
            name, kind = profile.fund_name, profile.fund_type
        else:
            name, kind = fund.fund_name, fund.fund_type
        try:
            industries, report_date = await self._industry_allocation(fund_code)
        except Exception:
            logger.exception("fund_sector_industry_evidence_unavailable", fund_code=fund_code)
            industries, report_date = [], None
        return FundSectorEvidence(
            fund_code=fund_code,
            fund_name=name,
            fund_type=kind,
            industries=industries,
            report_date=report_date,
        )

    async def get_managers(self, fund_code: str, limit: int = 50, refresh: bool = False) -> FundManagersResult:
        """基金经理历史及个人连续任职区间，缺数不回退现任姓名."""
        if not 1 <= limit <= 100:
            raise ValueError("经理历史limit必须在1至100之间")
        history, stamp, from_cache = await cached_disclosure(
            cache_key("fund_manager_history:v1", fund_code),
            FundManagerHistoryData,
            lambda: akshare_fund_provider.get_manager_history(fund_code),
            ttl=3600,
            refresh=refresh,
            valid=lambda data: data.fund_code == fund_code and bool(data.periods),
        )
        tenures = merge_manager_tenures(history.periods)
        warnings = [
            "来源页面提供团队管理区间；个人任职段仅合并同一经理连续区间，离任再任分别保留。",
            "至今表示来源页面标记的现任状态，获取时间不是任职起始时间或页面业务更新时间。",
        ]
        truncated = len(history.periods) > limit or len(tenures) > limit
        if truncated:
            warnings.append("任职区间或个人任职段已截断，不能称为全部历任列表；可增大limit至100。")
        return FundManagersResult(
            **history.model_dump(exclude={"periods"}),
            periods=history.periods[:limit],
            tenures=tenures[:limit],
            total_periods=len(history.periods),
            total_tenures=len(tenures),
            truncated=truncated,
            fetched_at=stamp,
            from_cache=from_cache,
            warnings=warnings,
        )

    async def get_announcements(self, request: FundAnnouncementsRequest) -> FundAnnouncementsResult:
        """按类型取50条一页并筛选日期/标题，公开扫描窗口和继续翻页方式."""
        categories = {
            "all": 0,
            "major_changes": 0,
            "operation": 1,
            "dividend": 2,
            "reports": 3,
            "personnel": 4,
            "sales": 5,
            "other": 6,
        }
        category = categories[request.category]
        page_size = 50
        page, stamp, from_cache = await cached_disclosure(
            cache_key("fund_announcements:v1", request.fund_code, str(category), str(request.page), str(page_size)),
            FundAnnouncementPage,
            lambda: akshare_fund_provider.get_announcements(request.fund_code, category, request.page, page_size),
            ttl=300,
            refresh=request.refresh,
            valid=lambda data: data.fund_code == request.fund_code
            and data.page == request.page
            and data.page_size == page_size
            and data.invalid_items == 0
            and data.missing_items == 0,
        )
        items = [
            row
            for row in page.items
            if (request.category != "major_changes" or row.major_change_hints)
            and (
                request.start_date is None
                or row.published_date is not None
                and row.published_date >= request.start_date
            )
            and (request.end_date is None or row.published_date is not None and row.published_date <= request.end_date)
            and (not request.keyword or request.keyword.strip().casefold() in row.title.casefold())
        ]
        items.sort(key=lambda row: (row.published_date or date.min, row.announcement_id), reverse=True)
        has_more = request.page * page_size < page.total
        warnings = [
            "返回公告索引与原文链接，未读取报告正文；发布日期不等于变更生效日。",
            "日期、关键词及重大变更筛选仅覆盖本次50条扫描页；无匹配不证明其他页不存在相关公告。",
        ]
        if request.category == "major_changes" or any(row.major_change_hints for row in items):
            warnings.append("重大变更标签是标题规则识别的待核验线索，不是官方完整分类，也不证明事件已经生效。")
        if page.invalid_items:
            warnings.append("部分公告字段无效已跳过，本页不完整且未缓存。")
        if page.missing_items:
            warnings.append("来源返回条数少于该页应有数量，本页有缺失且未缓存；不能按该页断言无匹配。")
        if any(row.published_date is None for row in page.items):
            warnings.append("部分公告发布日期未知；指定日期区间时这些条目不会纳入匹配。")
        if len(items) > request.limit:
            warnings.append("当前页匹配结果超过limit，请增大limit至50读取本页其余结果；next_page只指下一扫描页。")
        return FundAnnouncementsResult(
            **request.model_dump(exclude={"limit", "refresh"}),
            page_size=page_size,
            upstream_total=page.total,
            scanned_count=len(page.items) + page.invalid_items,
            matched_count=len(items),
            invalid_items=page.invalid_items,
            missing_items=page.missing_items,
            items=items[: request.limit],
            has_more=has_more,
            next_page=request.page + 1 if has_more and request.page < 1000 else None,
            fetched_at=stamp,
            from_cache=from_cache,
            warnings=warnings,
        )

    async def get_holdings(self, fund_code: str) -> FundHoldingsResponse:
        """披露的前十大重仓股，以及它们当前的行情.

        这里是实时读数据源而不是读 PostgreSQL：披露按季度更新且很稀疏，
        一个只在用户点开时才出现的页面，不该为"没人天天看的数据"
        背上同步任务、缓存失效逻辑和数据库迁移。
        数据源不可用时返回空页面，而不是让整个请求失败。
        """
        holdings = await self._disclosed_holdings(fund_code)
        industries, industries_as_of = await self._industry_allocation(fund_code)
        quarter, previous_quarter, items = summarize_holdings(holdings)
        if not items:
            return FundHoldingsResponse(
                fund_code=fund_code,
                quarter=quarter,
                previous_quarter=previous_quarter,
                industries=industries,
                industries_as_of=industries_as_of,
            )

        symbols = {item.stock_code: sina_symbol(item.stock_code) for item in items}
        # 数据源自己会把原始上市代码映射成行情代码；再喂给它带前缀的代码，
        # 它会把这些前缀再映射一遍，结果全都丢掉。
        quotes = {quote.symbol: quote for quote in await akshare_fund_provider.get_stock_quotes(list(symbols.keys()))}
        for item in items:
            quote = quotes.get(symbols.get(item.stock_code) or "")
            if quote is not None:
                item.price = quote.price
                item.change_pct = quote.change_pct
                item.quote_time = quote.quote_time

        return FundHoldingsResponse(
            fund_code=fund_code,
            quarter=quarter,
            previous_quarter=previous_quarter,
            items=items,
            industries=industries,
            industries_as_of=industries_as_of,
        )

    async def _industry_allocation(self, fund_code: str) -> tuple[list[FundIndustryItem], date | None]:
        """最近一次披露的行业权重，和重仓股表一样走缓存."""
        key = cache_key("fund_industries", fund_code)
        cached = await cache_service.get(key)
        if cached:
            payload = json.loads(cached)
            as_of = payload.get("as_of")
            return (
                [FundIndustryItem.model_validate(row) for row in payload["items"]],
                date.fromisoformat(as_of) if as_of else None,
            )
        try:
            rows = await akshare_fund_provider.get_industry_allocation(fund_code)
        except Exception:
            logger.exception("fund_industry_fetch_failed", fund_code=fund_code)
            return [], None
        items = [FundIndustryItem(industry=row.industry, weight=row.weight) for row in rows]
        as_of = rows[0].as_of if rows else None
        if items:
            await cache_service.set(
                key,
                json.dumps(
                    {
                        "items": [item.model_dump() for item in items],
                        "as_of": as_of.isoformat() if as_of else None,
                    },
                    ensure_ascii=False,
                ),
                ttl=_HOLDINGS_CACHE_TTL_SECONDS,
            )
        return items, as_of

    async def _disclosed_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        """读出最近两个披露季度；按季度更新，所以值得缓存."""
        key = cache_key("fund_holdings", fund_code)
        cached = await cache_service.get(key)
        if cached:
            return [FundExternalHolding.model_validate(row) for row in json.loads(cached)]
        try:
            holdings = await akshare_fund_provider.get_holdings(fund_code)
        except Exception:
            logger.exception("fund_holdings_fetch_failed", fund_code=fund_code)
            return []
        if holdings:
            await cache_service.set(
                key,
                json.dumps([holding.model_dump(mode="json") for holding in holdings], ensure_ascii=False),
                ttl=_HOLDINGS_CACHE_TTL_SECONDS,
            )
        return holdings

    def _compute_performance(self, points: list[NavPoint], end: date) -> FundPerformance:
        """从净值序列算出确定性的区间指标."""
        if not points:
            return FundPerformance()
        earliest = points[0].date
        return FundPerformance(
            return_1m=period_return(points, end, 1),
            return_3m=period_return(points, end, 3),
            return_6m=period_return(points, end, 6),
            return_1y=period_return(points, end, 12),
            return_3y=period_return(points, end, 36),
            return_since_inception=range_return(points, earliest, end),
            max_drawdown=max_drawdown(points),
            annualized_volatility=annualized_volatility(points),
        )

    # ------------------------------------------------------------------
    # 基金解析（供持仓导入使用）
    # ------------------------------------------------------------------

    async def name_directory(self) -> list[tuple[str, str]]:
        """可供截图里的名称去匹配的 (code, name) 名单.

        两种写法是刻意都留在名单里的：注册登记系统里这只基金叫
        天弘恒生科技ETF联接C，同步下来的主数据行却是它的完整注册名，
        而截图上印的是简称。按代码去重的话，长名字会把
        真正能匹配上的那种写法挤掉。
        """
        local = await fund_repository.all_names()
        if not AKSHARE_AVAILABLE:
            return local
        external = await akshare_fund_provider.get_name_directory()
        seen = set(local)
        return local + [pair for pair in external if pair not in seen]

    async def match_fund_names(self, name: str, limit: int = 5) -> list[NameMatch]:
        """拿名单跟一个名字做匹配，把最像的排在最前面."""
        return rank_names(name, await self.name_directory(), limit=limit)

    async def resolve_fund(self, raw_name: str | None, raw_code: str | None) -> tuple[Fund | None, float]:
        """把抽取到的原始名称/代码对应到标准的基金实体.

        Returns:
            (fund, confidence) —— 无法确定或存在歧义时 fund 为 None。
        """
        code_clean = (raw_code or "").strip()
        if code_clean.isdigit() and len(code_clean) == 6:
            fund = await self._get_fund_ensuring_data(code_clean)
            if fund is not None:
                return fund, 0.95
            return None, 0.0

        name_clean = (raw_name or "").strip()
        if not name_clean:
            return None, 0.0

        # 用排序匹配，而不是"名字必须完全一致"：截图上印的是 天弘恒生科技ETF联接(QDII)C，
        # 注册登记系统里把同一只基金写作 天弘恒生科技ETF联接C；
        # 而同一只基金的多个份额类别，
        # 绝不会靠猜测被合并成一个。
        winner = decide(await self.match_fund_names(name_clean))
        if winner is None:
            return None, 0.0
        fund = await self._get_fund_ensuring_data(winner.fund_code)
        if fund is None:
            return None, 0.0
        return fund, round(winner.score * 0.9, 2)

    # ------------------------------------------------------------------
    # 数据新鲜度
    # ------------------------------------------------------------------

    async def ensure_fund_data(self, fund_code: str) -> None:
        """保证本地有数据；净值过期就通过队列刷新.

        经搜索或榜单第一次进来的基金，名字用的是那个列表里的简称，净值只有一条 ——
        够列表展示，不够画图（走势要两个点），
        也不够导入时回读。这两种缺失在正常路径上都不会被升级：
        以前只有完全没听说过的基金才会去抓档案，
        而只有一条点的历史永远不会被判成"过期"。
        所以由第一个真正需要更多数据的视图来付这次全量同步。
        """
        fund = await fund_repository.get_fund(fund_code)
        if fund is None:
            await self._sync_now(fund_code)
            return

        if await self._needs_full_sync(fund):
            await cache_service.set(cache_key("fund_full_sync", fund_code), "1", ttl=_FULL_SYNC_RETRY_TTL_SECONDS)
            await self._sync_now(fund_code)

        if await fund_sync_service.is_nav_stale(fund_code):
            try:
                await fund_sync_service.enqueue_sync(fund_code)
            except Exception as e:
                logger.warning("fund_sync_enqueue_failed", fund_code=fund_code, error=str(e))

    async def _needs_full_sync(self, fund: Fund) -> bool:
        """这一行是不是只被省事的路径填过（从没做过完整同步）.

        这个标记之所以重要：今天才公布第一条净值的基金，
        本来就只有一个点是合理的，没有标记的话，
        每次打开这只基金都会去向 AKShare 要一份还不存在的历史。
        """
        profile_known = fund.company is not None or fund.manager_name is not None or fund.inception_date is not None
        if profile_known and await fund_repository.nav_count(fund.fund_code) >= _MIN_HISTORY_POINTS:
            return False
        return await cache_service.get(cache_key("fund_full_sync", fund.fund_code)) is None

    async def _sync_now(self, fund_code: str) -> None:
        """内联跑一次完整同步：档案、主数据行和净值历史."""
        try:
            await asyncio.wait_for(
                fund_sync_service.sync_fund(fund_code),
                timeout=settings.AKSHARE_TIMEOUT_SECONDS * 2,
            )
        except Exception:
            logger.exception("fund_inline_sync_failed", fund_code=fund_code)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _get_fund_ensuring_data(self, fund_code: str) -> Fund | None:
        """读取基金；完全不认识时尝试一次内联同步."""
        await self.ensure_fund_data(fund_code)
        return await fund_repository.get_fund(fund_code)

    async def _latest_nav_cached(self, fund_code: str) -> FundNav | None:
        """最新净值行的 cache-aside 读取（先查缓存，未命中回源再写回）."""
        key = cache_key("fund_latest_nav", fund_code)
        cached = await cache_service.get(key)
        if cached:
            return FundNav.model_validate(json.loads(cached))

        latest = await fund_repository.get_latest_nav(fund_code)
        if latest is not None:
            await cache_service.set(
                key,
                json.dumps(
                    {
                        "fund_code": latest.fund_code,
                        "nav_date": latest.nav_date.isoformat(),
                        "unit_nav": latest.unit_nav,
                        "accumulated_nav": latest.accumulated_nav,
                        "daily_return": latest.daily_return,
                        "fetched_at": latest.fetched_at.isoformat() if latest.fetched_at else None,
                    }
                ),
                ttl=_LATEST_NAV_CACHE_TTL_SECONDS,
            )
        return latest

    async def _user_flags(self, fund_code: str, user_id: int) -> tuple[bool, bool]:
        """判断该用户是否把这只基金加进了自选或持仓."""
        watchlisted, held = await self._user_flag_sets(user_id)
        return fund_code in watchlisted, fund_code in held

    async def _user_flag_sets(self, user_id: int) -> tuple[set[str], set[str]]:
        """该用户自选的基金代码集合，以及该用户持有的基金代码集合."""
        async with get_async_session() as session:
            watchlisted = set(
                (await session.execute(select(col(Watchlist.fund_code)).where(col(Watchlist.user_id) == user_id)))
                .scalars()
                .all()
            )
            held = set(
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
            return watchlisted, held

    @staticmethod
    def _to_points(history: list[FundNav]) -> list[NavPoint]:
        """把净值行转成分析用的数据点，按日期升序.

        单位净值为空的行直接丢弃，不按 0.0 读：
        序列里出现一个 0，以它为起点的每个区间
        都会报出 -100% 的区间收益和 -100% 的最大回撤。
        """
        return [NavPoint(date=row.nav_date, nav=row.unit_nav) for row in history if row.unit_nav is not None]

    @staticmethod
    def _encode_funds(funds: list[Fund]) -> str:
        """把搜索结果的公开部分序列化，放进共享缓存."""
        return json.dumps(
            [{"fund_code": fund.fund_code, "fund_name": fund.fund_name, "fund_type": fund.fund_type} for fund in funds]
        )

    @staticmethod
    def _decode_funds(raw: str) -> list[Fund]:
        """把缓存里的搜索结果还原成基金主数据行."""
        return [Fund.model_validate(entry) for entry in json.loads(raw)]


def _newest_page(history: list[FundNav], limit: int | None) -> tuple[list[FundNav], bool]:
    """在升序序列里保留最新的 `limit` 行，并说明还有更早的行剩下.

    行是按日期升序进来的，所以尾部就是最近的那一段，
    它前面的部分是下一页 —— 客户端用游标往回走就能取到。
    """
    if limit is None or len(history) <= limit:
        return history, False
    return history[-limit:], True


fund_service = FundService()
