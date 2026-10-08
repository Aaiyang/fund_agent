"""节假日在线适配器；查询 URL 只来自服务端配置，不接受模型指定地址."""

from typing import Any, Protocol

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.schemas.calendar import HolidayRecord, HolidayYear
from app.utils.clock import utc_now


class CalendarDataUnavailable(ValueError):
    """数据源没有提供该年安排，不能按周末推测法定节假日."""


class HolidayCalendarProvider(Protocol):
    """可替换的在线日历数据源."""

    async def get_year(self, year: int) -> HolidayYear:
        """获取并验证年度放假及调休记录."""
        ...


def _retryable(exc: BaseException) -> bool:
    """仅重试传输故障、429 与 5xx，不重试参数/格式错误."""
    return isinstance(exc, httpx.TransportError) or (
        isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500)
    )


def parse_year_payload(payload: Any, year: int, source: str) -> HolidayYear:
    """严格校验日期键、年份与真假布尔值；年度数据缺失必须显式失败."""
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise ValueError("holiday provider returned an unsuccessful payload")
    raw = payload.get("holiday")
    if not isinstance(raw, dict):
        raise ValueError("holiday provider returned an invalid year")
    if not raw:
        raise CalendarDataUnavailable(f"{year} 年节假日安排尚未公布或数据源尚未提供")
    records: list[HolidayRecord] = []
    for key, value in raw.items():
        record = HolidayRecord.model_validate(value)
        if record.day.year != year or key != record.day.strftime("%m-%d"):
            raise ValueError("holiday provider date and year do not match")
        records.append(record)
    # 最低完整性检查；不能据此保证上游没有遗漏其他节日或调休。
    known = {record.day.strftime("%m-%d"): record for record in records}
    if not all(key in known and known[key].holiday for key in ("01-01", "10-01")):
        raise CalendarDataUnavailable(f"{year} 年日历数据不完整，暂不能可靠判断工作日")
    return HolidayYear(
        year=year, records=sorted(records, key=lambda record: record.day), fetched_at=utc_now(), source=source
    )


class TimorHolidayProvider:
    """Timor 在线年度日历；无需 API Key；可用服务器配置替换自部署端点."""

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=2),
        reraise=True,
    )
    async def get_year(self, year: int) -> HolidayYear:
        """获取年度放假/补班记录；服务端限定超时和响应大小."""
        source = f"{settings.HOLIDAY_API_BASE_URL.rstrip('/')}/year/{year}/"
        async with httpx.AsyncClient(timeout=settings.HOLIDAY_API_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.get(source)
            response.raise_for_status()
            if len(response.content) > 256 * 1024:
                raise ValueError("holiday provider response is too large")
            return parse_year_payload(response.json(), year, source)
