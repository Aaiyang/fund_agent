"""get_fund_snapshot — 一只基金的概览：基本资料、最新净值与区间业绩."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import drop_nones, tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import ToolRuntimeError, get_tool_runtime
from app.services.fund_service import fund_service
from app.utils.clock import business_today

# 净值日期落后超过这个自然日数就标记为 stale：基金净值 T+1 公布，
# 再长就说明同步链路滞后了。
_STALE_NAV_DAYS = 3


@tool
@tool_result
async def get_fund_snapshot(
    fund_code: Annotated[str, Field(description="6 位基金代码，例如 005827")],
) -> str:
    """查询一只基金的概览：基金名称、类型、基金公司、经理、规模、最新净值与近期业绩（近 1 月/3 月/6 月/1 年收益等）。用于回答“005827 是什么基金”“这只基金表现怎么样”这类问题."""
    code = validate_fund_code(fund_code)
    runtime = get_tool_runtime()
    detail = await fund_service.get_detail(code, runtime.user_id)
    if detail is None:
        raise ToolRuntimeError("FUND_NOT_FOUND", f"未找到基金 {code}")

    data = drop_nones(
        {
            "fund_code": detail.fund_code,
            "fund_name": detail.fund_name,
            "fund_type": detail.fund_type,
            "company": detail.company,
            "manager_name": detail.manager_name,
            "inception_date": detail.inception_date.isoformat() if detail.inception_date else None,
            "asset_size": detail.asset_size,
            "latest_nav": detail.latest_nav,
            "accumulated_nav": detail.accumulated_nav,
            "nav_date": detail.nav_date.isoformat() if detail.nav_date else None,
            "daily_return": detail.daily_return,
            "performance": detail.performance.model_dump(exclude_none=True) if detail.performance else None,
        }
    )

    warnings: list[str] = []
    stale = False
    if detail.nav_date is not None:
        days_old = (business_today() - detail.nav_date).days
        if days_old > _STALE_NAV_DAYS:
            stale = True
            warnings.append(f"最新净值日期为 {detail.nav_date.isoformat()}，距今天 {days_old} 天，可能不是最新数据")

    as_of = detail.source_as_of or detail.nav_date
    return ToolResult.ok(
        data,
        source=detail.source,
        as_of=as_of.isoformat() if as_of else None,
        stale=stale,
        warnings=warnings,
    ).to_text()
