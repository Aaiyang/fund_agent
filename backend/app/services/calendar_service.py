"""民用日历查询：默认在线刷新，只缓存成功数据，故障时明确标记旧快照."""

import asyncio
import re
from datetime import date, timedelta

from app.core.cache import cache_key, cache_service
from app.core.config import settings
from app.core.logging import logger
from app.integrations.holiday_calendar import HolidayCalendarProvider, TimorHolidayProvider
from app.schemas.calendar import CalendarDay, CalendarRequest, CalendarResponse, HolidayRecord, HolidayYear
from app.utils.clock import business_today, utc_now

_CACHE_FRESH_SECONDS = 300
_CACHE_FALLBACK_SECONDS = 6 * 3600
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def build_calendar_request(
    start_date: str | None = None, end_date: str | None = None, year: int | None = None, refresh: bool = True
) -> CalendarRequest:
    """默认查业务时区的今天；日期范围最多 31 天，全年只列特殊安排."""
    if year is not None:
        if start_date is not None or end_date is not None or not 2000 <= year <= 2100:
            raise ValueError("year 必须在 2000～2100 之间，且不能与 start_date/end_date 同时使用")
        return CalendarRequest(mode="year", start_date=date(year, 1, 1), end_date=date(year, 12, 31), refresh=refresh)
    if end_date is not None and start_date is None:
        raise ValueError("指定 end_date 时也必须指定 start_date")

    def parse(value: str) -> date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("日期必须使用 YYYY-MM-DD 格式")
        return date.fromisoformat(value)

    start = parse(start_date) if start_date is not None else business_today()
    end = parse(end_date) if end_date is not None else start
    if not 2000 <= start.year <= end.year <= 2100 or not 0 <= (end - start).days < 31:
        raise ValueError("日期年份必须在 2000～2100，且结束日期不能早于开始日期，范围最多 31 天")
    return CalendarRequest(mode="date" if start == end else "range", start_date=start, end_date=end, refresh=refresh)


def classify_calendar_day(day: date, record: HolidayRecord | None) -> CalendarDay:
    """调休优先于周末；未列入已校验年度安排的日期按星期分类."""
    weekend = day.weekday() >= 5
    if record:
        kind = "holiday" if record.holiday else "makeup_workday"
        name = record.name
        working = not record.holiday
    else:
        kind = "weekend" if weekend else "workday"
        name = _WEEKDAYS[day.weekday()]
        working = not weekend
    return CalendarDay(
        date=day,
        weekday=day.weekday() + 1,
        kind=kind,
        name=name,
        is_workday=working,
        is_weekend=weekend,
        related_holiday=record.target if record else None,
    )


class CalendarService:
    """共享公开日历数据，不包含任何用户信息."""

    def __init__(self, provider: HolidayCalendarProvider | None = None) -> None:
        """允许测试注入外部数据源."""
        self.provider = provider or TimorHolidayProvider()

    async def _get_year(self, year: int, refresh: bool) -> tuple[HolidayYear, bool, bool]:
        """返回快照、是否命中缓存、是否因在线失败降级."""
        key = cache_key("calendar:timor:v1", settings.HOLIDAY_API_BASE_URL, str(year))
        cached: HolidayYear | None = None
        raw = await cache_service.get(key)
        if raw:
            try:
                candidate = HolidayYear.model_validate_json(raw)
                age = (utc_now() - candidate.fetched_at).total_seconds()
                if candidate.year == year and 0 <= age < _CACHE_FALLBACK_SECONDS:
                    cached = candidate
                    if not refresh and age < _CACHE_FRESH_SECONDS:
                        return cached, True, False
            except Exception:
                logger.exception("calendar_cache_invalid", year=year)
        try:
            snapshot = await self.provider.get_year(year)
            await cache_service.set(key, snapshot.model_dump_json(by_alias=True), ttl=_CACHE_FALLBACK_SECONDS)
            logger.info("calendar_year_fetched", year=year, record_count=len(snapshot.records))
            return snapshot, False, False
        except Exception:
            if cached:
                logger.exception("calendar_using_stale_cache", year=year)
                return cached, True, True
            raise

    async def query(self, request: CalendarRequest) -> CalendarResponse:
        """最多查询两个年份，跨年结果一并校验后输出，不发布部分成功数据."""
        snapshots = await asyncio.gather(
            *[
                self._get_year(year, request.refresh)
                for year in range(request.start_date.year, request.end_date.year + 1)
            ]
        )
        records = {record.day: record for snapshot, _, _ in snapshots for record in snapshot.records}
        if request.mode == "year":
            days = [classify_calendar_day(day, records[day]) for day in sorted(records)]
        else:
            days = [
                classify_calendar_day(day, records.get(day))
                for day in (
                    request.start_date + timedelta(days=index)
                    for index in range((request.end_date - request.start_date).days + 1)
                )
            ]
        stale = any(old for _, _, old in snapshots)
        warnings = ["这是中国大陆民用放假/调休日历，不能直接作为证券交易日历；调休周末上班不代表交易所开市。"]
        if request.mode == "year":
            warnings.append("全年模式只列放假和调休补班安排，不列普通工作日与普通周末。")
        if stale:
            warnings.append("在线获取失败，使用六小时以内的历史快照；本次数据未经实时更新，请核对官方公告。")
        return CalendarResponse(
            timezone=settings.FUND_BUSINESS_TZ,
            mode=request.mode,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            sources=[snapshot.source for snapshot, _, _ in snapshots],
            fetched_at_utc=min(snapshot.fetched_at for snapshot, _, _ in snapshots),
            cache_used=any(cached for _, cached, _ in snapshots),
            stale=stale,
            warnings=warnings,
        )


calendar_service = CalendarService()
