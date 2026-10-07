"""get_fund_holdings — 一只基金的定期披露持仓与行业配置."""

from datetime import date
from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.services.fund_service import fund_service


@tool
@tool_result
async def get_fund_holdings(
    fund_code: Annotated[str, Field(description="6 位基金代码，例如 005827")],
) -> str:
    """查询一只基金最近一期披露的前十大重仓股与行业配置。注意：基金持仓是季度定期披露数据，不是实时持仓。用于“这只基金主要持有哪些股票”这类问题."""
    code = validate_fund_code(fund_code)
    response = await fund_service.get_holdings(code)

    if not response.items:
        return ToolResult.fail(
            "DATA_NOT_AVAILABLE",
            f"基金 {code} 暂无披露的持仓数据（新基金或数据源未覆盖）",
        ).to_text()

    data = {
        "fund_code": code,
        "report_date": response.quarter,
        "previous_quarter": response.previous_quarter,
        "top_holdings": [
            {
                "stock_code": item.stock_code,
                "stock_name": item.stock_name,
                "weight": item.weight,
                "weight_change": item.weight_change,
                "is_new": item.is_new,
            }
            for item in response.items
        ],
        "industry_allocation": [{"industry": item.industry, "weight": item.weight} for item in response.industries]
        or None,
    }

    warnings = []
    if response.quarter:
        warnings.append(f"持仓为 {response.quarter} 定期披露数据，非实时持仓")

    as_of = response.industries_as_of
    return ToolResult.ok(
        data,
        source="fund_service",
        as_of=as_of.isoformat() if isinstance(as_of, date) else None,
        warnings=warnings,
    ).to_text()
