"""股票研究真实数据工具."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.services.stock_research_service import stock_research_service


@tool
@tool_result
async def get_stock_analysis_data(symbol: str) -> ToolResult:
    """获取股票公开报价、近一年价格风险指标、公司概况和客户端图表引用.

    必须传带市场前缀的股票代码，例如sh600519、sz000001、hk00700、usAAPL。
    不猜名称对应代码，不支持指数；没有用户股票持仓、完整财报和即时新闻。
    图表只复制chart_code_block，不生成价格序列。数值缺失不能补零。
    """
    data = await stock_research_service.collect(symbol)
    if not data["available"]:
        return ToolResult.fail("DATA_NOT_AVAILABLE", "股票研究数据暂不可用，请稍后重试")
    return ToolResult.ok(data, source="market_service", warnings=data["warnings"])
