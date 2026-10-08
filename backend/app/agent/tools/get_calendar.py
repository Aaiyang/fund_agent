"""实时日历工具：查询中国大陆节假日、普通周末和调休补班."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.integrations.holiday_calendar import CalendarDataUnavailable
from app.services.calendar_service import build_calendar_request, calendar_service


@tool
@tool_result
async def get_calendar(
    start_date: str | None = None,
    end_date: str | None = None,
    year: int | None = None,
    refresh: bool = True,
) -> str:
    """实时查询中国大陆放假与调休安排.

    无参数查今天；start_date/end_date 使用 YYYY-MM-DD，范围最多31天。
    year 查询全年放假和补班安排，不能与日期参数同时用。
    默认 refresh=true 在线获取，false 可用5分钟内缓存。
    判断某天是否放假、周末是否补班、假期安排时优先用本工具。
    民用调休工作日不等于证券交易日；数据未公布时明确返回不可用，禁止猜测。
    """
    try:
        query = build_calendar_request(start_date, end_date, year, refresh)
    except ValueError as exc:
        return ToolResult.fail("INVALID_ARGUMENT", str(exc)).to_text()
    try:
        result = await calendar_service.query(query)
    except CalendarDataUnavailable as exc:
        return ToolResult.fail("DATA_NOT_AVAILABLE", str(exc)).to_text()
    return ToolResult.ok(
        result.model_dump(mode="json", exclude={"warnings", "stale"}),
        source=";".join(result.sources),
        as_of=result.end_date.isoformat(),
        stale=result.stale,
        warnings=result.warnings,
    ).to_text()
