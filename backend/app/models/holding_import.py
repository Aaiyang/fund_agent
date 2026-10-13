"""持仓导入模型：导入批次与批次下的待确认条目.

这两张表跑的是 解析 → 复核 → 确认 → 应用 这条流程，只算一层审计留痕 —— 持仓的权威
事实表是 portfolio_position。截图原图不存在这里，也不存在 PostgreSQL 的任何地方。
"""

from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, JSON

from app.models.base import BaseModel
from app.utils.clock import utc_now


def _new_import_id() -> str:
    return uuid4().hex


class HoldingImport(BaseModel, table=True):
    """一次手动录入或截图识别的持仓导入批次.

    状态流转：UPLOADED → PARSING → REVIEW_REQUIRED → CONFIRMED → APPLIED，
    PARSE_FAILED 与 CANCELLED 是表示失败的终态。
    """

    __tablename__ = "holding_import"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=_new_import_id, primary_key=True, max_length=32)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int | None = Field(default=None, foreign_key="portfolio_account.id", index=True)
    # Agent 上传的批次绑定会话；普通持仓页面导入保持 None。
    chat_session_id: str | None = Field(default=None, index=True)
    import_type: str = Field(max_length=20)  # 取值：MANUAL（手动录入）/ SCREENSHOT（截图识别）
    status: str = Field(default="UPLOADED", max_length=30, index=True)

    image_count: int = Field(default=0)
    image_hashes: list | dict | None = Field(default=None, sa_type=JSON)
    items_detected: int = Field(default=0)
    items_confirmed: int = Field(default=0)

    error_message: str | None = Field(default=None, max_length=500)
    started_at: datetime | None = Field(default=None)
    confirmed_at: datetime | None = Field(default=None)
    applied_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )


class HoldingImportItem(BaseModel, table=True):
    """一条等待用户确认的待导入持仓.

    user_action 记下用户的处置：UPDATE（采纳导入）、SKIP（跳过），或 EDIT
    （确认前先自己改过字段）。
    """

    __tablename__ = "holding_import_item"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    import_id: str = Field(foreign_key="holding_import.id", index=True)
    raw_fund_name: str | None = Field(default=None, max_length=200)
    matched_fund_code: str | None = Field(default=None, max_length=12, index=True)
    matched_fund_name: str | None = Field(default=None, max_length=200)

    market_value: float | None = Field(default=None)
    shares: float | None = Field(default=None)
    cost_amount: float | None = Field(default=None)
    average_cost_nav: float | None = Field(default=None)
    profit_loss: float | None = Field(default=None)
    profit_loss_rate: float | None = Field(default=None)

    confidence: float | None = Field(default=None)
    validation_status: str = Field(default="pending", max_length=30)
    validation_issues: list | dict | None = Field(default=None, sa_type=JSON)
    user_action: str | None = Field(default=None, max_length=20)
