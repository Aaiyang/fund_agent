"""定投计划 API 的 schema."""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.analytics.schedule import Frequency
from app.schemas.base import BaseResponse


class AutoInvestPlanItem(BaseModel):
    """一条定投计划，附下一次应扣款的日期."""

    id: int
    account_id: int
    fund_code: str
    fund_name: str | None = None
    amount: float
    frequency: Frequency
    run_day: int
    start_date: date
    end_date: date | None = None
    active: bool
    last_run_date: date | None = None
    next_due: date | None = None


class AutoInvestPlansResponse(BaseResponse):
    """GET /auto-invest/plans 响应体."""

    items: list[AutoInvestPlanItem]
    total: int
    # 组装这份列表期间补写下来的期数。读列表这个动作就是结算时机，
    # 因为后台 worker 可能压根没在跑。
    settled: int = 0


class AutoInvestPlanCreateRequest(BaseModel):
    """POST /auto-invest/plans 请求体."""

    account_id: int
    fund_code: str = Field(min_length=6, max_length=6)
    amount: float = Field(gt=0)
    frequency: Frequency = "weekly"
    run_day: int = Field(default=1, ge=1, le=31, description="每周几（1-7）或每月几号（1-31）")
    start_date: date
    end_date: date | None = None

    @field_validator("fund_code")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("基金代码需要是 6 位数字")
        return value


class AutoInvestPlanUpdateRequest(BaseModel):
    """PATCH /auto-invest/plans/{id} 请求体；传 null 的字段保持原样."""

    amount: float | None = Field(default=None, gt=0)
    frequency: Frequency | None = None
    run_day: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None
