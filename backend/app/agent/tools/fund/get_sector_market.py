"""查询真实行业/概念板块的最新公开行情."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import ToolRuntimeError, tool_result
from app.agent.tools.result import ToolResult
from app.schemas.sector import SectorMarketRequest, SectorScope
from app.services.sector_service import sector_service


@tool
@tool_result
async def get_sector_market(
    keyword: Annotated[
        str,
        Field(
            min_length=1, max_length=64, description="板块名称、关键词或真实BK代码；优先用get_fund_sectors返回的代码"
        ),
    ],
    sector_type: Annotated[SectorScope, Field(description="industry行业、concept概念或all")] = "all",
    limit: Annotated[int, Field(ge=1, le=5, description="最多返回5个匹配板块")] = 5,
    refresh: Annotated[bool, Field(description="默认true在线刷新；false允许15秒内成功报价缓存")] = True,
) -> ToolResult:
    """查询中国A股行业/概念板块最新点位、涨跌点数、涨跌幅及真实报价时间.

    查询基金关联板块的涨跌时先调用 get_fund_sectors，再按返回BK代码查询。
    支持直接按板块名查询。change_pct单位为百分点，1.2表示+1.2%。
    公开行情可能延迟，非交易时段可能是最近报价；逐条检查quote_time、stale及error_code。
    失败或时间未知不能冒充今日实时，板块涨跌不能当作基金收益。
    """
    if not keyword.strip():
        raise ToolRuntimeError("INVALID_ARGUMENT", "请输入板块名称或代码")
    response = await sector_service.market(
        SectorMarketRequest(keyword=keyword, sector_type=sector_type, limit=limit, refresh=refresh)
    )
    if not response.sectors:
        if response.unavailable_catalogs:
            return ToolResult.fail("DATA_NOT_AVAILABLE", "板块目录暂不可用，无法确认匹配结果")
        return ToolResult.fail("SECTOR_NOT_FOUND", "没有匹配到板块，请核对名称或BK代码")
    if all(item.price is None for item in response.sectors):
        return ToolResult.fail("DATA_NOT_AVAILABLE", "暂无法取得匹配板块行情，不使用历史值替代")
    times = [item.quote_time for item in response.sectors if item.quote_time is not None]
    return ToolResult.ok(
        response.model_dump(mode="json", exclude={"warnings", "source"}),
        source=response.source,
        as_of=min(times).isoformat() if times else None,
        stale=any(item.stale or item.error_code is not None for item in response.sectors),
        warnings=response.warnings,
    )
