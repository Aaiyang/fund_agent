"""get_watchlist — 用户的基金自选清单与阶段表现."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import drop_nones, tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.services.watchlist_service import watchlist_service


@tool
@tool_result
async def get_watchlist(
    group_id: Annotated[int | None, Field(description="可选：只看某个自选分组；不填则看全部分组")] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 50,
) -> str:
    """查询当前用户的自选基金清单：基金代码/名称、最新净值、日/周/月/季/半年/近一年区间收益、是否已持有、所属分组与净值时效。按用户自选顺序返回。用于“我的自选有哪些”“自选里哪只表现最好”“这个分组里有什么”这类问题。只读当前用户本人的自选，不等同于持仓，也不代表买卖建议."""
    runtime = get_tool_runtime()
    items = await watchlist_service.list_funds(runtime.user_id, group_id)

    warnings: list[str] = []
    if len(items) > limit:
        warnings.append(f"共 {len(items)} 只自选，仅返回前 {limit} 只")
    items = items[:limit]

    rows = [
        drop_nones(
            {
                "fund_code": item.fund_code,
                "fund_name": item.fund_name,
                "fund_type": item.fund_type,
                "latest_nav": item.latest_nav,
                "nav_date": item.nav_date.isoformat() if item.nav_date else None,
                "daily_return": item.daily_return,
                "weekly_return": item.weekly_return,
                "monthly_return": item.monthly_return,
                "quarterly_return": item.quarterly_return,
                "semiannual_return": item.semiannual_return,
                "annual_return": item.annual_return,
                "is_held": item.is_held,
                "nav_is_updated": item.is_updated,
                "groups": item.groups,
                "group_ids": item.group_ids,
            }
        )
        for item in items
    ]

    stale = any(not item.is_updated for item in items)
    if stale:
        warnings.append("部分自选基金的净值可能不是最新，引用阶段收益时需说明数据日期")

    as_of = max((item.nav_date for item in items if item.nav_date), default=None)
    return ToolResult.ok(
        {
            "watchlist_count": len(rows),
            "return_unit": "percentage_point",
            "watchlist": rows,
        },
        source="watchlist_service",
        as_of=as_of.isoformat() if as_of else None,
        stale=stale,
        warnings=warnings,
    ).to_text()
