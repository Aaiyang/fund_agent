"""持仓导入 API 的 schema."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.integrations.holdings.base import ManualPositionInput
from app.schemas.base import BaseResponse


class ManualImportRequest(BaseModel):
    """POST /holding-imports/manual 请求体."""

    account_id: int
    positions: list[ManualPositionInput]


class ImportCandidate(BaseModel):
    """截图名称仍可能指到的某一只基金，供确认页一键选择."""

    fund_code: str
    fund_name: str
    score: float


class ImportItemOut(BaseModel):
    """一条待确认的导入明细，带确认页要用的差异字段."""

    id: int
    raw_fund_name: str | None = None
    matched_fund_code: str | None = None
    matched_fund_name: str | None = None
    market_value: float | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    confidence: float | None = None
    validation_status: str
    validation_issues: list[str] = []
    user_action: str | None = None
    # 差异预览：当前持仓、识别结果、导入之后三者对照
    current_market_value: float | None = None
    current_version: int | None = None
    # 读这一行时才现算、从不落库：没匹配上的名字往往是同一只基金的几个份额
    # 类别，候选列表得跟着名册此刻的样子走，而不是解析当时名册的样子。
    candidates: list[ImportCandidate] = []


class ImportDetail(BaseModel):
    """一个导入批次，可带上明细条目."""

    id: str
    account_id: int | None
    import_type: str
    status: str
    image_count: int = 0
    items_detected: int = 0
    items_confirmed: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    confirmed_at: datetime | None = None
    applied_at: datetime | None = None
    created_at: datetime | None = None
    items: list[ImportItemOut] = []


class ImportDetailResponse(BaseResponse):
    """GET /holding-imports/{import_id} 以及手动导入的响应体."""

    import_batch: ImportDetail


class ImportHistoryResponse(BaseResponse):
    """GET /holding-imports/history 响应体."""

    items: list[ImportDetail]
    total: int


class ScreenshotImportAccepted(BaseResponse):
    """POST /holding-imports/screenshots 响应体（HTTP 202）."""

    import_id: str
    status: str
    image_count: int


class ImportItemUpdateRequest(BaseModel):
    """PATCH /holding-imports/{import_id}/items/{item_id} 请求体."""

    user_action: str | None = Field(default=None, pattern="^(UPDATE|SKIP|EDIT)$")
    fund_code: str | None = Field(default=None, max_length=12)
    market_value: float | None = Field(default=None, ge=0)
    shares: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    average_cost_nav: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    profit_loss_rate: float | None = None


class ImportConfirmResponse(BaseResponse):
    """POST /holding-imports/{import_id}/confirm 响应体."""

    import_id: str
    applied: int
    skipped: int
