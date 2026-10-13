"""identify_event_portfolio_links — 只读当前用户持仓的可解释事件关联."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.schemas.market_event import EventPortfolioLinkRequest
from app.services.event_portfolio_service import EventReferenceMissing, event_portfolio_service
from app.services.portfolio_service import AccountNotFoundError


@tool(args_schema=EventPortfolioLinkRequest)
@tool_result
async def identify_event_portfolio_links(
    event_ids: list[str],
    account_id: int | None = None,
    position_limit: int = 20,
) -> ToolResult:
    """识别公开事件与当前登录用户真实持仓的潜在关联，仅接收get_market_events返回的event_id.

    最多5事件、50持仓行，默认按市值检查前20行，账户必须属于当前用户。
    区分历史披露行业、基金名称线索与宏观/市场背景；影响方向固定unknown。
    不接受用户身份、任意新闻正文或URL，不外传持仓金额，不预测收益，不修改持仓。
    未匹配、截断或资料不可用不能解释为没有影响。过期引用需重新查询事件。
    """
    runtime = get_tool_runtime()
    try:
        result = await event_portfolio_service.identify(
            runtime.user_id,
            EventPortfolioLinkRequest(
                event_ids=event_ids,
                account_id=account_id,
                position_limit=position_limit,
            ),
        )
    except EventReferenceMissing:
        return ToolResult.fail("EVENT_NOT_AVAILABLE", "事件引用缺失或过期，请先调用get_market_events重新获取event_id")
    except AccountNotFoundError:
        return ToolResult.fail("PERMISSION_DENIED", "无法访问该账户的持仓")
    return ToolResult.ok(
        result.model_dump(mode="json", exclude={"warnings"}),
        source="public_event_and_portfolio_evidence",
        warnings=result.warnings,
    )
