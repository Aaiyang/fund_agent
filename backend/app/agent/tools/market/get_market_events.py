"""get_market_events — 固定公开来源的有界宏观、行业与市场报道窗口."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.integrations.fund_data.event_client import EventDataUnavailable
from app.schemas.market_event import EventScope, MarketEventsRequest
from app.services.market_event_service import market_event_service


@tool(args_schema=MarketEventsRequest)
@tool_result
async def get_market_events(
    scope: EventScope = "all",
    lookback_hours: int = 24,
    keyword: str | None = None,
    important_only: bool = True,
    limit: int = 20,
    refresh: bool = False,
) -> ToolResult:
    """获取近期宏观、行业和市场事件的财联社公开报道、来源链接、发布时间及event_id.

    默认筛选来源A/B重点标记，最多扫描最近100条，范围all/macro/industry/market。
    分类与主题来自规则，仅是研究线索，不代表独立核验、全部重大事件或发生/生效时间。
    关键词在本地筛选，覆盖区间和部分结果明确返回。空匹配不能说没有事件。
    用户持仓关联需将本工具返回的1–5个event_id交给identify_event_portfolio_links。
    放假、调休和补班必须使用get_calendar，不能用本工具代替。
    """
    if keyword is not None and not keyword.strip():
        return ToolResult.fail("INVALID_ARGUMENT", "keyword不能仅为空白")
    try:
        result = await market_event_service.query(
            MarketEventsRequest(
                scope=scope,
                lookback_hours=lookback_hours,
                keyword=keyword,
                important_only=important_only,
                limit=limit,
                refresh=refresh,
            )
        )
    except EventDataUnavailable:
        return ToolResult.fail("DATA_NOT_AVAILABLE", "暂未取得可核验事件，不能据此断言没有重大事件")
    return ToolResult.ok(
        result.model_dump(mode="json", exclude={"warnings"}),
        source="cls_telegraph",
        as_of=min(event.published_at for event in result.events).isoformat() if result.events else None,
        warnings=result.warnings,
    )
