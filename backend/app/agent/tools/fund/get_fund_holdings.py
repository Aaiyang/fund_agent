"""get_fund_holdings — 一只基金的定期披露持仓与行业配置."""

from datetime import date
from math import isfinite
from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.schemas.fund_analysis import FundHoldingsCard, FundHoldingsCardItem
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
                "price": getattr(item, "price", None),
                "change_pct": getattr(item, "change_pct", None),
                "quote_time": getattr(item, "quote_time", None),
            }
            for item in response.items
        ],
        "industry_allocation": [{"industry": item.industry, "weight": item.weight} for item in response.industries]
        or None,
    }

    warnings = [
        "个股price/change_pct仅为可用时的最近报价，change_pct单位为百分点；quote_time未知或日期不一致时不能用于当期收益归因。"
    ]
    if response.quarter:
        warnings.append(f"持仓为 {response.quarter} 定期披露数据，非实时持仓")

    # Preserve the full research payload above; the card only includes renderable disclosure weights.
    card_items: list[FundHoldingsCardItem] = []
    seen: set[str] = set()
    for item in response.items[:10]:
        name = item.stock_name or item.stock_code
        if (
            item.weight is None
            or not isfinite(item.weight)
            or not 0 <= item.weight <= 100
            or not item.stock_code.strip()
            or len(item.stock_code) > 32
            or not name.strip()
            or len(name) > 100
            or item.stock_code in seen
        ):
            continue
        seen.add(item.stock_code)
        card_items.append(FundHoldingsCardItem(stock_code=item.stock_code, stock_name=name, weight=item.weight))
    data["holdings_code_block"] = None
    if card_items and len(response.quarter or "") <= 80:
        card_warnings = []
        if len(card_items) < len(response.items):
            card_warnings.append("部分披露记录的权重缺失、无效或重复，卡片仅显示可核验记录；不能视为全部持仓。")
        card = FundHoldingsCard(
            fund_code=code,
            report_date=response.quarter or "披露期未知",
            items=card_items,
            warnings=card_warnings,
        )
        data["holdings_code_block"] = "```fund-holdings\n" + card.model_dump_json() + "\n```"

    as_of = response.industries_as_of
    return ToolResult.ok(
        data,
        source="fund_service",
        as_of=as_of.isoformat() if isinstance(as_of, date) else None,
        warnings=warnings,
    ).to_text()
