"""Holding import API schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.integrations.holdings.base import ManualPositionInput
from app.schemas.base import BaseResponse


class ManualImportRequest(BaseModel):
    """POST /holding-imports/manual request."""

    account_id: int
    source_app: str | None = Field(default=None, max_length=50)
    positions: list[ManualPositionInput]


class ImportCandidate(BaseModel):
    """One fund a screenshot name could still be, offered for one-tap choice."""

    fund_code: str
    fund_name: str
    score: float


class ImportItemOut(BaseModel):
    """One pending import row with diff fields for the confirm page."""

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
    # Diff preview: current holdings vs recognized vs after import
    current_market_value: float | None = None
    current_version: int | None = None
    # Recomputed when a row is read, never stored: an unresolved name is
    # usually several share classes of one fund, and the list has to reflect
    # the register as it is now rather than as it was when the parse ran.
    candidates: list[ImportCandidate] = []


class ImportDetail(BaseModel):
    """One import batch with optional item payloads."""

    id: str
    account_id: int
    import_type: str
    source_app: str | None = None
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
    """GET /holding-imports/{import_id} and manual-import responses."""

    import_batch: ImportDetail


class ImportHistoryResponse(BaseResponse):
    """GET /holding-imports/history response."""

    items: list[ImportDetail]
    total: int


class ScreenshotImportAccepted(BaseResponse):
    """POST /holding-imports/screenshots response (HTTP 202)."""

    import_id: str
    status: str
    image_count: int


class ImportItemUpdateRequest(BaseModel):
    """PATCH /holding-imports/{import_id}/items/{item_id} request."""

    user_action: str | None = Field(default=None, pattern="^(UPDATE|SKIP|EDIT)$")
    fund_code: str | None = Field(default=None, max_length=12)
    market_value: float | None = Field(default=None, ge=0)
    shares: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    average_cost_nav: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    profit_loss_rate: float | None = None


class ImportConfirmResponse(BaseResponse):
    """POST /holding-imports/{import_id}/confirm response."""

    import_id: str
    applied: int
    skipped: int
