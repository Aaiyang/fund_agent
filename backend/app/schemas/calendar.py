"""中国大陆民用节假日日历的查询、数据快照与输出模型."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints, model_validator


class CalendarRequest(BaseModel):
    """已验证的查询范围；全年模式只返回放假与补班记录."""

    mode: Literal["date", "range", "year"]
    start_date: date
    end_date: date
    refresh: bool = True


class HolidayRecord(BaseModel):
    """数据源的特殊日期，holiday=false 表示调休补班."""

    day: date = Field(alias="date")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    holiday: StrictBool
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


class HolidayYear(BaseModel):
    """只缓存校验成功的年度快照，保留真实获取时间."""

    year: int
    records: list[HolidayRecord]
    fetched_at: datetime
    source: str

    @model_validator(mode="after")
    def validate_records(self) -> "HolidayYear":
        """缓存恢复和数据源输入均校验年度一致性及必要完整性."""
        dates = [record.day for record in self.records]
        if len(dates) != len(set(dates)) or any(day.year != self.year for day in dates):
            raise ValueError("duplicate dates or mismatched holiday year")
        holidays = {record.day.strftime("%m-%d") for record in self.records if record.holiday}
        if not {"01-01", "10-01"}.issubset(holidays):
            raise ValueError("incomplete holiday year")
        return self


class CalendarDay(BaseModel):
    """工作日属性指民用日历，不能当成证券交易日历."""

    date: date
    weekday: int
    kind: Literal["workday", "weekend", "holiday", "makeup_workday"]
    name: str
    is_workday: bool
    is_weekend: bool
    related_holiday: str | None = None


class CalendarResponse(BaseModel):
    """返回数据来源、获取时间与缓存状态，禁止把旧数据当成实时结果."""

    region: str = "中国大陆"
    timezone: str
    mode: Literal["date", "range", "year"]
    start_date: date
    end_date: date
    days: list[CalendarDay]
    sources: list[str]
    fetched_at_utc: datetime
    cache_used: bool = False
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
