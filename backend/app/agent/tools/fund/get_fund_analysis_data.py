"""净值研究数据与不可执行的fund-chart代码块."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.schemas.fund_analysis import FundAnalysisRequest, FundChartReference
from app.services.fund_analysis_service import fund_analysis_service


@tool(args_schema=FundAnalysisRequest)
@tool_result
async def get_fund_analysis_data(fund_code: str) -> ToolResult:
    """取得近一年真实单位净值分析指标与fund-chart JSON代码块，供fund-analysis技能使用.

    仅输入六位基金代码，返回研究指标及仅含基金标识的fund-chart v2代码块。
    图表由移动端复用基金详情组件，直接查询后端净值和基准，不经模型传输序列。
    日点计算未复权净值变化/回撤，保留实际覆盖范围、缺口和数据日期。
    指标比值0.1表示10%；range_position_ratio是高低区间线性位置，不是估值分位。
    净值变化不等于含分红的总回报；个人成本另查get_positions，不在公开图中保存。
    chart_code_block须逐字嵌入回复，不添加points、URL、成本或身份字段。
    数据不足仍可返回基金引用，客户端显示实际加载/空/失败状态，不虚构走势。
    """
    result = await fund_analysis_service.get_data(FundAnalysisRequest(fund_code=fund_code))
    data = result.model_dump(mode="json", exclude={"chart", "warnings", "stale"})
    # Research metrics stay available to the model; chart series never enter its context.
    reference = FundChartReference(fund_code=fund_code)
    data["chart_code_block"] = "```fund-chart\n" + reference.model_dump_json() + "\n```"
    return ToolResult.ok(
        data,
        source="fund_service",
        as_of=result.observed_to.isoformat() if result.observed_to else None,
        stale=result.stale,
        warnings=result.warnings,
    )
