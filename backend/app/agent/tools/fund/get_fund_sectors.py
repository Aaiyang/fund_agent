"""查询基金关联板块，保留披露证据与名称线索的区别."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.services.sector_service import sector_service


@tool
@tool_result
async def get_fund_sectors(
    fund_code: Annotated[str, Field(description="6位基金代码，保留前导零")],
    limit: Annotated[int, Field(ge=1, le=5, description="最多返回5个关联板块")] = 5,
) -> ToolResult:
    """查询基金可能关联的中国A股行业/概念板块，返回真实BK代码供 get_sector_market 查询涨跌.

    disclosed_industry为最新定期披露行业与板块目录的精确名称匹配，权重单位为百分点。
    fund_name_hint仅为基金名称主题线索，待核验，不证明跟踪指数或实际持仓。
    基金可跨多个板块，宽行业不能强行映射到具体板块；无证据返回未知。
    境外、债券、货币等基金不建立A股板块归属；板块涨跌不等于基金净值涨跌。
    """
    response = await sector_service.fund_sectors(validate_fund_code(fund_code), limit)
    if response is None:
        return ToolResult.fail("DATA_NOT_AVAILABLE", "未取得基金资料，暂无法查询关联板块")
    return ToolResult.ok(
        response.model_dump(mode="json", exclude={"warnings"}),
        source="fund_disclosure_and_sector_catalog",
        as_of=response.report_date.isoformat() if response.report_date else None,
        warnings=response.warnings,
    )
