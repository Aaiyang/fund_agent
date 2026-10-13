"""get_positions — 用户的基金持仓明细."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import drop_nones, tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.services.portfolio_service import portfolio_service


@tool
@tool_result
async def get_positions(
    account_id: Annotated[int | None, Field(description="可选：只看某个账户；不填则看全部账户")] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> str:
    """查询当前用户的基金持仓明细：每只基金的份额、成本、市值、盈亏、占比等，按市值从大到小排列。用于“我现在有哪些基金”“我最大的持仓是什么”这类问题。数据只来自用户本人的持仓记录."""
    runtime = get_tool_runtime()
    items = await portfolio_service.list_positions(runtime.user_id, account_id)
    # 按市值从大到小排序（无市值视为最小），便于模型先看到最重要的持仓
    items.sort(key=lambda item: item.market_value if item.market_value is not None else -1.0, reverse=True)

    warnings: list[str] = []
    if len(items) > limit:
        warnings.append(f"共 {len(items)} 只持仓，仅返回市值最大的前 {limit} 只")
    items = items[:limit]

    rows = [
        drop_nones(
            {
                "fund_code": item.fund_code,
                "fund_name": item.fund_name,
                "account_id": item.account_id,
                "shares": item.shares,
                "cost_amount": item.cost_amount,
                "average_cost_nav": getattr(item, "average_cost_nav", None),
                "average_cost_nav_derived": getattr(item, "average_cost_nav_derived", False),
                "market_value": item.market_value,
                "profit_loss": item.profit_loss,
                "profit_loss_rate": item.profit_loss_rate,
                "weight": item.position_ratio,
                "daily_profit_loss": item.daily_profit_loss,
                "nav_date": item.nav_date.isoformat() if item.nav_date else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        )
        for item in items
    ]

    as_of = max((item.nav_date for item in items if item.nav_date), default=None)
    return ToolResult.ok(
        {"position_count": len(rows), "positions": rows},
        source="portfolio_service",
        as_of=as_of.isoformat() if as_of else None,
        warnings=warnings,
    ).to_text()
