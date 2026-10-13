"""按基金代码查询历任基金经理和任职时间."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.services.fund_service import fund_service


@tool
@tool_result
async def get_fund_managers(
    fund_code: Annotated[str, Field(description="6位基金代码，保留前导零")],
    limit: Annotated[int, Field(ge=1, le=100, description="原始区间和个人任职段各最多返回此数量，默认50")] = 50,
    refresh: Annotated[bool, Field(description="true强制在线更新，false允许一小时内成功缓存")] = False,
) -> ToolResult:
    """按基金代码查询历任基金经理、任职起止日期、来源任职期间及现任标记.

    periods是原始团队区间，多人共同管理保留多经理；tenures合并同一经理连续区间。
    离任后再任分别保留，end_date为空仅在is_current=true时表示来源标记至今。
    来源页面未给出业务更新时间；fetched_at为UTC获取时间，不能称为任职起始时间。
    注意truncated和warnings，不把当前经理姓名当作全部历史，不推断个人任职回报。
    """
    response = await fund_service.get_managers(validate_fund_code(fund_code), limit=limit, refresh=refresh)
    return ToolResult.ok(
        response.model_dump(mode="json", exclude={"warnings"}),
        source="eastmoney_fund_manager_history",
        warnings=response.warnings,
    )
