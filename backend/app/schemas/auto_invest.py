"""Auto-invest plan API schemas."""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.analytics.schedule import Frequency
from app.schemas.base import BaseResponse


class AutoInvestPlanItem(BaseModel):
    """One standing plan, with the day it is next due."""

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
    """GET /auto-invest/plans response."""

    items: list[AutoInvestPlanItem]
    total: int
    # Installments written while building this list. Reading the plans is what
    # catches a plan up, because the worker may not be running.
    settled: int = 0


class AutoInvestPlanCreateRequest(BaseModel):
    """POST /auto-invest/plans request."""

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
    """PATCH /auto-invest/plans/{id} request. A null field leaves it intact."""

    amount: float | None = Field(default=None, gt=0)
    frequency: Frequency | None = None
    run_day: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None
