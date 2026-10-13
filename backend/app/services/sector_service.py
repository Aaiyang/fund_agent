"""基金板块证据匹配与板块行情服务，拒绝将宽行业或名称线索当作实时归属."""

import asyncio
import json
import re

from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.integrations.fund_data.models import MarketExternalQuote
from app.integrations.fund_data.sector_client import (
    SINA_BOARD_SOURCE,
    fetch_sina_sector_board,
    fetch_sector_catalog,
    fetch_sector_quote,
)
from app.schemas.sector import (
    FundSectorEvidence,
    FundSectorLink,
    FundSectorsResult,
    SectorBoardItem,
    SectorBoardKind,
    SectorBoardOrder,
    SectorBoardResponse,
    SectorBoardSort,
    SectorCatalog,
    SectorItem,
    SectorKind,
    SectorMarketRequest,
    SectorMarketResult,
    SectorQuote,
    SectorScope,
)
from app.services.fund_service import fund_service
from app.utils.clock import business_now, utc_now
from app.utils.market_quote_policy import MAINLAND_MARKET_TZ, finite_number, normalize_realtime_index

_CATALOG_TTL = 24 * 3600
_QUOTE_TTL = 15
# 板块榜是整表一次取回，排名和条数都在本地做，所以 30 秒内换榜不重复打上游。
_BOARD_TTL = 30
_CATALOG_LOCKS: dict[SectorKind, asyncio.Lock] = {"industry": asyncio.Lock(), "concept": asyncio.Lock()}
_UNSUPPORTED_FUNDS = re.compile(r"QDII|债券|货币|REIT|FOF|纳斯达克|标普|恒生|港股|海外|全球", re.I)
_GENERIC_THEMES = {"成长", "价值", "创新", "精选", "优选", "优势", "融资融券", "基金重仓", "机构重仓"}


def _canonical(text: str) -> str:
    """仅归一化空格、大小写和行业后缀，不猜测同义分类."""
    return re.sub(r"\s+", "", text).removesuffix("行业").casefold()


def match_fund_sectors(evidence: FundSectorEvidence, catalog: list[SectorItem], limit: int) -> FundSectorsResult:
    """仅做保守、可解释的名称匹配，不用 LLM 强行建立跨分类体系映射."""
    result = FundSectorsResult(
        **evidence.model_dump(),
        warnings=[
            "基金可能跨多个行业；披露权重不是实时持仓。板块涨跌不等于基金净值涨跌，不据此计算基金当日收益。",
            "名称线索待核验，不证明跟踪该指数或当前实际配置；不同分类体系无法精确匹配时保留未知。",
        ],
    )
    if not evidence.industries:
        result.warnings.append("未取得基金披露行业，名称线索不能代替持仓证据。")
    if result.industries and result.report_date is None:
        result.warnings.append("披露行业缺少截止日期，时效无法核验。")
    if _UNSUPPORTED_FUNDS.search((evidence.fund_type or "") + evidence.fund_name):
        result.unmatched_industries = evidence.industries
        result.warnings.append("本工具仅提供中国A股板块，债券、货币、境外或其他不适用基金暂不建立板块关联。")
        return result
    links: dict[str, FundSectorLink] = {}
    for industry in sorted(evidence.industries, key=lambda row: finite_number(row.weight) or 0, reverse=True):
        matches = [
            item
            for item in catalog
            if item.sector_type == "industry" and _canonical(item.name) == _canonical(industry.industry)
        ]
        if not matches:
            result.unmatched_industries.append(industry)
        for item in matches:
            links[item.sector_code] = FundSectorLink(
                **item.model_dump(),
                evidence_type="disclosed_industry",
                evidence=industry.industry,
                disclosed_weight=finite_number(industry.weight),
                report_date=evidence.report_date,
            )
    for item in sorted(catalog, key=lambda row: (-len(row.name), row.sector_code)):
        name = _canonical(item.name)
        if len(name) >= 2 and name not in _GENERIC_THEMES and name in _canonical(evidence.fund_name):
            links.setdefault(
                item.sector_code,
                FundSectorLink(
                    **item.model_dump(),
                    evidence_type="fund_name_hint",
                    evidence=evidence.fund_name,
                ),
            )
    result.total_matches = len(links)
    result.sectors = list(links.values())[:limit]
    result.truncated = len(links) > limit
    if not result.sectors:
        result.warnings.append("未取得可核验板块关联；不能按基金代码或宽行业猜测具体板块。")
    return result


class SectorService:
    """公开目录缓存与有时效的板块报价；所有故障保留为未知."""

    async def _catalog(self, kind: SectorKind) -> SectorCatalog | None:
        key = cache_key("sector_catalog:v1", kind)
        async with _CATALOG_LOCKS[kind]:
            try:
                raw = await cache_service.get(key)
                if raw:
                    saved = SectorCatalog.model_validate_json(raw)
                    age = (utc_now() - saved.fetched_at).total_seconds() if saved.fetched_at.tzinfo is None else -1
                    if (
                        0 <= age < _CATALOG_TTL
                        and saved.items
                        and all(item.sector_type == kind for item in saved.items)
                    ):
                        return saved
            except Exception:
                logger.exception("sector_catalog_cache_read_failed", sector_type=kind)
            try:
                rows = await fetch_sector_catalog(kind)
                if not rows:
                    return None
                result = SectorCatalog(items=rows, fetched_at=utc_now())
            except Exception:
                logger.exception("sector_catalog_fetch_failed", sector_type=kind)
                return None
            try:
                await cache_service.set(key, result.model_dump_json(), ttl=_CATALOG_TTL)
            except Exception:
                logger.exception("sector_catalog_cache_write_failed", sector_type=kind)
            return result

    async def catalog(self, scope: SectorScope = "all") -> tuple[list[SectorItem], list[SectorKind]]:
        """独立获取行业/概念目录，单类故障不伪装成完整无匹配."""
        kinds: list[SectorKind] = ["industry", "concept"] if scope == "all" else [scope]
        results = await asyncio.gather(*(self._catalog(kind) for kind in kinds))
        items = [item for catalog in results if catalog for item in catalog.items]
        missing: list[SectorKind] = [kind for kind, result in zip(kinds, results, strict=True) if result is None]
        return items, missing

    async def fund_sectors(self, fund_code: str, limit: int = 5) -> FundSectorsResult | None:
        """基金证据由 FundService 提供，不直接访问基金仓库或适配器."""
        evidence = await fund_service.get_sector_evidence(fund_code)
        if evidence is None:
            return None
        catalog, unavailable = await self.catalog()
        result = match_fund_sectors(evidence, catalog, limit)
        result.unavailable_catalogs = unavailable
        if unavailable:
            result.warnings.append("部分板块目录获取失败，关联结果可能不完整。")
        return result

    async def _quote(self, item: SectorItem, refresh: bool) -> SectorQuote:
        key = cache_key("sector_quote:v1", item.sector_type, item.sector_code)
        cached = None
        if not refresh:
            try:
                raw = await cache_service.get(key)
                if raw:
                    candidate = SectorQuote.model_validate_json(raw)
                    if candidate.fetched_at and candidate.fetched_at.tzinfo is None:
                        age = (utc_now() - candidate.fetched_at).total_seconds()
                        if (
                            0 <= age < _QUOTE_TTL
                            and candidate.sector_code == item.sector_code
                            and candidate.sector_type == item.sector_type
                            and candidate.change_pct is not None
                            and candidate.trade_date == business_now().astimezone(MAINLAND_MARKET_TZ).date()
                            and not candidate.stale
                            and not candidate.error_code
                        ):
                            cached = candidate
            except Exception:
                logger.exception("sector_quote_cache_read_failed", sector_code=item.sector_code)
        try:
            if cached:
                external = MarketExternalQuote(
                    symbol=item.sector_code,
                    kind="index",
                    price=cached.price,
                    change=cached.change,
                    change_pct=cached.change_pct,
                    quote_time=cached.quote_time.isoformat() if cached.quote_time else None,
                )
                fetched_at = cached.fetched_at
            else:
                external = await fetch_sector_quote(item)
                fetched_at = utc_now()
            normalized = normalize_realtime_index(external, item.name, business_now())
            if normalized is None:
                return SectorQuote(**item.model_dump(), error_code="DATA_NOT_AVAILABLE")
            result = SectorQuote(
                **item.model_dump(),
                price=normalized.price,
                change=normalized.change,
                change_pct=normalized.change_pct,
                quote_time=normalized.quote_time,
                trade_date=normalized.trade_date,
                freshness=normalized.freshness,
                stale=normalized.stale,
                fetched_at=fetched_at,
                from_cache=cached is not None,
            )
        except Exception:
            logger.exception("sector_quote_fetch_failed", sector_code=item.sector_code)
            return SectorQuote(**item.model_dump(), error_code="UPSTREAM_ERROR")
        if cached is None and not result.stale and result.change_pct is not None:
            try:
                await cache_service.set(key, result.model_dump_json(), ttl=_QUOTE_TTL)
            except Exception:
                logger.exception("sector_quote_cache_write_failed", sector_code=item.sector_code)
        return result

    async def market(self, request: SectorMarketRequest) -> SectorMarketResult:
        """先在真实目录匹配，再查询最多五个板块；输入不进入 URL 或 secid."""
        keyword = request.keyword.strip()
        if not keyword:
            raise ValueError("请输入板块名称、关键词或真实BK代码")
        catalog, unavailable = await self.catalog(request.sector_type)
        exact = [
            item for item in catalog if _canonical(keyword) in {_canonical(item.name), item.sector_code.casefold()}
        ]
        matches = exact or [item for item in catalog if _canonical(keyword) in _canonical(item.name)]
        selected = matches[: request.limit]
        quotes = await asyncio.gather(*(self._quote(item, request.refresh) for item in selected))
        result = SectorMarketResult(
            keyword=keyword,
            requested_date=business_now().astimezone(MAINLAND_MARKET_TZ).date(),
            sectors=list(quotes),
            total_matches=len(matches),
            truncated=len(matches) > request.limit,
            unavailable_catalogs=unavailable,
            warnings=[
                "仅为中国A股行业/概念板块公开快照，可能延迟；按各板块报价时间核验，交易所日历未核验。",
                "板块涨跌不等于基金涨跌；行业和概念板块分类与基金披露行业可能不同。",
            ],
        )
        if unavailable:
            result.warnings.append("部分板块目录不可用，不能据此断言该板块不存在。")
        if result.truncated:
            result.warnings.append("匹配结果已截断，请使用返回的板块代码进一步精确查询。")
        if any(row.stale or row.error_code for row in quotes):
            result.warnings.append("部分板块行情过期、时间未知或获取失败，不可冒充今日实时涨跌。")
        if any(row.price is not None and row.change_pct is None for row in quotes):
            result.warnings.append("部分板块涨跌幅未知，不可补成0或推断涨跌方向。")
        return result

    async def _board_items(self, kind: SectorBoardKind) -> list[SectorBoardItem]:
        """整表取一次板块榜，原始解析结果缓存 30 秒；失败返回空表不补数."""
        key = cache_key("sector_board:v1", kind)
        try:
            raw = await cache_service.get(key)
            if raw:
                return [SectorBoardItem.model_validate(row) for row in json.loads(raw)]
        except Exception:
            logger.exception("sector_board_cache_read_failed", sector_type=kind)
        try:
            items = await fetch_sina_sector_board(kind)
        except Exception:
            logger.exception("sector_board_fetch_failed", sector_type=kind)
            return []
        try:
            payload = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False)
            await cache_service.set(key, payload, ttl=_BOARD_TTL)
        except Exception:
            logger.exception("sector_board_cache_write_failed", sector_type=kind)
        return items

    async def board(
        self, kind: SectorBoardKind, order: SectorBoardOrder, sort: SectorBoardSort, limit: int
    ) -> SectorBoardResponse:
        """板块榜：按选定指标排名；该指标缺失的板块不参与排名，固定在榜尾."""
        items = await self._board_items(kind)

        def metric(item: SectorBoardItem) -> float | None:
            return item.change_pct if sort == "change_pct" else item.amount

        known = [item for item in items if metric(item) is not None]
        unknown = [item for item in items if metric(item) is None]
        known.sort(key=lambda item: metric(item) or 0.0, reverse=order == "desc")

        label = "涨跌幅" if sort == "change_pct" else "成交额"
        warnings = [
            "板块涨跌不等于基金涨跌；新浪行业/概念分类与基金披露行业可能不同。",
            "上游不带报价时间戳，fetched_at 只是抓取时刻，不能当开市证明。",
        ]
        if not items:
            warnings.append("板块涨跌榜暂时取不到，这里返回空列表而不是补数。")
        elif unknown:
            warnings.append(f"{len(unknown)} 个板块{label}缺失，已排在榜尾。")

        ranked = known[:limit]
        ranked += unknown[: limit - len(ranked)]
        return SectorBoardResponse(
            source=SINA_BOARD_SOURCE,
            sector_type=kind,
            order=order,
            sort=sort,
            fetched_at=utc_now(),
            items=ranked,
            total_available=len(known),
            warnings=warnings,
        )


sector_service = SectorService()
