"""基金对比的统一窗口计算入口."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.schemas.fund_comparison import FundComparisonRequest
from app.services.fund_comparison_service import fund_comparison_service


@tool(args_schema=FundComparisonRequest)
@tool_result
async def get_fund_comparison_data(fund_codes: list[str]) -> ToolResult:
    """对比2–3只已确认基金的共同窗口净值变化、观察回撤和年化波动率.

    仅传六位基金代码，不传名称、身份、金额或净值序列。默认近一年请求窗口。
    代码对齐真实日期并计算；部分数据或无共同窗口保留gaps，不能替换为各自区间排名。
    指标为比值0.1=10%，未分红复权，不是投资者总回报，不判断费用、相关性或未来收益。
    rows中的fund-chart引用可逐字展示，图表各自查询，不能称为叠加比较曲线。
    """
    data = await fund_comparison_service.get_data(FundComparisonRequest(fund_codes=fund_codes))
    return ToolResult.ok(
        data.model_dump(mode="json"),
        source="fund_service",
        as_of=data.common_to.isoformat() if data.common_to else None,
        stale=data.stale,
    )
