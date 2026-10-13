"""在本地关联公开事件与当前用户真实持仓，外部来源不收到持仓或资产金额."""

import asyncio

from app.analytics.event_links import link_event
from app.core.logging import logger
from app.schemas.market_event import EventPortfolioLinkRequest, EventPortfolioLinksResult, EventPositionLink
from app.schemas.sector import FundSectorEvidence
from app.services.fund_service import fund_service
from app.services.market_event_service import market_event_service
from app.services.portfolio_service import portfolio_service
from app.utils.clock import utc_now
from app.utils.market_quote_policy import finite_number


class EventReferenceMissing(ValueError):
    """引用不存在、过期或不可核验，必须重新查询公开事件."""


class EventPortfolioService:
    """只读按用户隔离的持仓，每次重查，不缓存或写入私有分析."""

    async def identify(self, user_id: int, request: EventPortfolioLinkRequest) -> EventPortfolioLinksResult:
        """先解析来源引用，再读取用户持仓；最多50行、5事件、返回50条关联."""
        events, missing = await market_event_service.resolve(request.event_ids)
        if missing:
            raise EventReferenceMissing("事件引用不可用，请重新调用get_market_events获取event_id")
        positions = await portfolio_service.list_positions(user_id, request.account_id)
        positions.sort(key=lambda item: finite_number(item.market_value) or 0, reverse=True)
        selected = positions[: request.position_limit]
        semaphore = asyncio.Semaphore(4)
        unavailable: list[str] = []

        async def evidence(code: str) -> tuple[str, FundSectorEvidence | None]:
            async with semaphore:
                try:
                    fund = await fund_service.get_sector_evidence(code)
                    if fund is None:
                        unavailable.append(code)
                    return code, fund
                except Exception:
                    logger.exception("event_portfolio_fund_evidence_failed", fund_code=code)
                    unavailable.append(code)
                    return code, None

        funds = dict(
            await asyncio.gather(*(evidence(code) for code in dict.fromkeys(row.fund_code for row in selected)))
        )
        links: list[EventPositionLink] = []
        for position in selected:
            fund = funds.get(position.fund_code)
            if fund is None:
                continue
            for event in events:
                links.extend(link_event(event, fund, position.account_id))
        warnings = [
            "关联是规则研究线索，不是因果证明、涨跌预测或买卖建议；影响方向和收益幅度均未知。",
            "披露行业可能过时，基金名称不证明当前暴露；宏观/市场背景不等于具体持仓关联。",
            "未匹配或基金资料缺失不代表不受影响；不覆盖股票穿透、完整地区/久期/汇率暴露。",
        ]
        if len(positions) > len(selected):
            warnings.append("持仓检查已按市值截断，未检查其余持仓；可增大position_limit至50。")
        if unavailable:
            warnings.append("部分基金资料不可用，相关持仓未完成匹配。")
        if len(links) > 50:
            warnings.append("关联列表只返回前50条，可减少事件或账户范围后查询。")
        return EventPortfolioLinksResult(
            events=events,
            account_id=request.account_id,
            total_positions=len(positions),
            checked_positions=len(selected),
            skipped_positions=len(positions) - len(selected),
            unavailable_funds=sorted(set(unavailable)),
            associations=links[:50],
            total_associations=len(links),
            truncated=len(positions) > len(selected) or len(links) > 50,
            holdings_checked_at=utc_now(),
            warnings=warnings,
        )


event_portfolio_service = EventPortfolioService()
