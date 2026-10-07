"""get_portfolio — 用户的组合汇总：总市值、成本、收益."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.services.portfolio_service import portfolio_service


@tool
@tool_result
async def get_portfolio(
    account_id: Annotated[int | None, Field(description="可选：只统计某个账户；不填则统计全部账户")] = None,
) -> str:
    """查询当前用户的基金组合汇总：持仓数量、总市值、总成本、总收益与收益率、今日盈亏。用于“我的组合现在多少钱”“我整体赚了多少”这类问题。数据只来自用户本人的持仓记录."""
    runtime = get_tool_runtime()
    summary = await portfolio_service.get_summary(runtime.user_id, account_id)

    as_of = summary.data_updated_at
    return ToolResult.ok(
        {
            "fund_count": summary.fund_count,
            "total_market_value": summary.total_market_value,
            "total_cost": summary.total_cost,
            "total_profit_loss": summary.total_profit_loss,
            "total_profit_loss_rate": summary.total_profit_loss_rate,
            "daily_profit_loss": summary.daily_profit_loss,
            "data_updated_at": as_of.isoformat() if as_of else None,
        },
        source="portfolio_service",
        as_of=as_of.isoformat() if as_of else None,
    ).to_text()
