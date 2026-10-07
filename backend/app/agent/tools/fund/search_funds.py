"""search_funds — 按名称、简称或 6 位代码搜索基金."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.services.fund_service import fund_service


@tool
@tool_result
async def search_funds(
    keyword: Annotated[str, Field(min_length=1, description="基金名称、简称或 6 位代码")],
    limit: Annotated[int, Field(ge=1, le=20)] = 10,
) -> str:
    """按基金名称、简称或 6 位代码搜索基金，返回匹配的基金代码、名称与类型。用于用户提到基金名字或代码但需要确认具体是哪只基金时."""
    runtime = get_tool_runtime()
    items = await fund_service.search(keyword.strip(), runtime.user_id)

    if not items:
        return ToolResult.ok(
            {"keyword": keyword, "matches": []},
            source="fund_service",
        ).to_text()

    data = {
        "keyword": keyword,
        "matches": [
            {
                "fund_code": item.fund_code,
                "fund_name": item.fund_name,
                "fund_type": item.fund_type,
            }
            for item in items[:limit]
        ],
    }
    warnings = []
    if len(items) > limit:
        warnings.append(f"共 {len(items)} 条匹配，仅返回相关度最高的前 {limit} 条")
    return ToolResult.ok(data, source="fund_service", warnings=warnings).to_text()
