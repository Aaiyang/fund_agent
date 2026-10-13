"""get_realtime_market — 今日主要 A 股指数最新报价与涨跌."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.schemas.market import RealtimeIndexCode, RealtimeMarketRequest
from app.services.market_service import market_service


@tool
@tool_result
async def get_realtime_market(
    index_codes: Annotated[
        list[RealtimeIndexCode] | None,
        Field(min_length=1, max_length=14, description="可选主要A股指数代码，不填查询全部14只；不支持个股或URL"),
    ] = None,
    refresh: Annotated[bool, Field(description="默认true在线刷新；false允许使用15秒内完整成功快照")] = True,
) -> ToolResult:
    """获取今天市场整体行情的主要指数快照：点位、涨跌点数、涨跌幅、昨收、开高低、成交额和报价时间.

    覆盖上证、深证、沪深300、创业板、科创50、中证500/1000、北证50等14只主要A股指数。
    查询“今天大盘怎么样”“现在各指数涨跌”优先用本工具，不用收盘历史或联网搜索代替。
    change_pct单位为百分点（1.2表示+1.2%）；报价时间为Asia/Shanghai，获取时间另列UTC。
    公开报价可能延迟，非交易时段返回最近报价，旧日/延迟/缺时间标记stale，不能冒充今日实时。
    部分数据缺失明确返回missing_indexes，不编造涨跌家数、资金流向或把重叠指数成交额相加。
    """
    response = await market_service.get_realtime_quotes(
        RealtimeMarketRequest(index_codes=index_codes, refresh=refresh)
    )
    if response is None:
        return ToolResult.fail("DATA_NOT_AVAILABLE", "暂时无法获取有效指数实时快照，不使用历史收盘代替")
    # 全局 as_of 采用最早可核验报价；每只指数的时间仍保留，避免掩盖滞后条目。
    times = [item.quote_time for item in response.indexes if item.quote_time is not None]
    return ToolResult.ok(
        response.model_dump(mode="json", exclude={"warnings", "stale", "source"}),
        source=response.source,
        as_of=min(times).isoformat() if times else None,
        stale=response.stale,
        warnings=response.warnings,
    )
