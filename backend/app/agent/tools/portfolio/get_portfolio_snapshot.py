"""一次读取研究账本快照，不触发导入或交易."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.services.portfolio_service import portfolio_service


@tool
@tool_result
async def get_portfolio_snapshot(account_id: int | None = None) -> ToolResult:
    """读取当前用户完整轻量持仓快照与同范围汇总，空持仓不等于读取失败。只读不导入."""
    runtime = get_tool_runtime()
    snapshot = await portfolio_service.research_snapshot(runtime.user_id, account_id)
    data = snapshot.model_dump(mode="json", exclude={"summary": {"daily_profit_loss"}})
    if any(row.cost_amount is None for row in snapshot.positions):
        data["summary"].pop("total_cost", None)
        data["summary"].pop("total_profit_loss_rate", None)
    if any(row.profit_loss is None for row in snapshot.positions):
        data["summary"].pop("total_profit_loss", None)
    return ToolResult.ok(
        data,
        source="portfolio_service",
        warnings=snapshot.warnings,
    )
