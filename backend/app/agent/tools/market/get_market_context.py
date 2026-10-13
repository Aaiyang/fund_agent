"""get_market_context — 基准指数收盘与涨跌概览."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.services.market_service import market_service
from app.utils.clock import business_today

# 与 market_service 自身判断数据回补时使用的天数阈值一致。
_STALE_DAYS = 3


@tool
@tool_result
async def get_market_context() -> str:
    """查询基准指数最新日线收盘概览：上证、深证、沪深300、创业板、国债指数。来自历史收盘序列；盘中或今日实时涨跌请用 get_realtime_market，不能用本工具替代实时行情."""
    quotes = await market_service.get_quotes()
    if not quotes:
        return ToolResult.fail("DATA_NOT_AVAILABLE", "暂时无法获取指数行情数据").to_text()

    as_of = max((quote.trade_date for quote in quotes if quote.trade_date), default=None)
    warnings: list[str] = []
    stale = False
    if as_of is not None:
        days_old = (business_today() - as_of).days
        if days_old > _STALE_DAYS:
            stale = True
            warnings.append(f"最新行情日期为 {as_of.isoformat()}，距今天 {days_old} 天（可能处于休市）")

    return ToolResult.ok(
        {
            "indexes": [
                {
                    "index_code": quote.index_code,
                    "name": quote.name,
                    "close": quote.close,
                    "change_pct": quote.change_pct,
                    "trade_date": quote.trade_date.isoformat() if quote.trade_date else None,
                }
                for quote in quotes
            ]
        },
        source="market_service",
        as_of=as_of.isoformat() if as_of else None,
        stale=stale,
        warnings=warnings,
    ).to_text()
