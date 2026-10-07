"""get_fund_history — 一只基金的净值历史，支持区间与粒度采样."""

from datetime import date
from typing import Annotated, Literal

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import ToolRuntimeError
from app.schemas.fund import NavRange
from app.services.fund_service import fund_service

# 即使 daily 粒度也限制返回点数上限，防止 3 年的日线序列撑爆上下文预算。
_MAX_POINTS = 500


def _sample(points: list[dict], granularity: Literal["daily", "weekly", "monthly"]) -> list[dict]:
    """把升序的日线序列降采样到指定粒度.

    每个周期只保留最后一个交易日（人们引用的收盘价）。daily 原样通过。
    """
    if granularity == "daily":
        return points
    bucket: dict[tuple, dict] = {}
    for point in points:
        day = date.fromisoformat(point["date"])
        key = day.isocalendar()[:2] if granularity == "weekly" else (day.year, day.month)
        bucket[key] = point
    return [bucket[key] for key in sorted(bucket)]


@tool
@tool_result
async def get_fund_history(
    fund_code: Annotated[str, Field(description="6 位基金代码，例如 005827")],
    range_key: Annotated[
        Literal["1m", "3m", "6m", "1y", "3y", "all"] | None,
        Field(description="命名区间：近 1 月/3 月/6 月/1 年/3 年/全部"),
    ] = None,
    start_date: Annotated[
        str | None, Field(description="起始日期 YYYY-MM-DD（与 end_date 搭配，二选一于 range_key）")
    ] = None,
    end_date: Annotated[str | None, Field(description="结束日期 YYYY-MM-DD")] = None,
    granularity: Annotated[
        Literal["daily", "weekly", "monthly"], Field(description="数据粒度，默认 weekly 避免返回过多数据点")
    ] = "weekly",
) -> str:
    """查询一只基金在指定区间的净值走势，默认按周采样。用于“最近一年走势如何”“今年以来涨了多少”这类问题."""
    code = validate_fund_code(fund_code)
    if range_key is None and start_date is None:
        raise ToolRuntimeError(
            "INVALID_ARGUMENT",
            "需要提供 range_key（如 1y）或 start_date 来指定查询区间",
        )

    parsed_start = date.fromisoformat(start_date) if start_date else None  # noqa: E501
    parsed_end = date.fromisoformat(end_date) if end_date else None
    range_typed: NavRange | None = range_key  # 与 NavRange 的字面值完全一致

    response = await fund_service.get_nav_history(
        code,
        start_date=parsed_start,
        end_date=parsed_end,
        range_key=range_typed,
    )
    points = [
        {"date": point.nav_date.isoformat(), "unit_nav": point.unit_nav}
        for point in response.points
        if point.unit_nav is not None
    ]
    total_daily = len(points)
    points = _sample(points, granularity)

    warnings: list[str] = []
    if total_daily > len(points):
        warnings.append(f"原始 {total_daily} 个交易日，已按 {granularity} 采样为 {len(points)} 个点")
    if response.has_more:
        warnings.append(f"数据源还有更早的历史（合计 {response.total} 条），当前区间外未返回")
    if len(points) > _MAX_POINTS:
        warnings.append(f"数据点过多，仅保留最近 {_MAX_POINTS} 个")
        points = points[-_MAX_POINTS:]

    as_of = points[-1]["date"] if points else None
    return ToolResult.ok(
        {"fund_code": code, "granularity": granularity, "points": points},
        source="fund_service",
        as_of=as_of,
        warnings=warnings,
    ).to_text()
