"""供网页和移动端共用的 Agent 图片导入与人工复核协议."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.base import BaseResponse
from app.schemas.holding_import import ImportItemOut

ImportId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class HoldingImportReview(BaseModel):
    """结构化 HITL 卡片，图 checkpoint 保存它，客户端刷新可恢复."""

    kind: Literal["holding_import_review"] = "holding_import_review"
    interrupt_id: str = ""
    import_id: ImportId
    account_id: int
    image_count: int
    review_digest: str
    items: list[ImportItemOut]
    notice: str = "确认后按基金覆盖此账户的持仓快照并记录调整流水；未出现在截图中的其他持仓不会删除。"


class HoldingImportDecision(BaseModel):
    """仅由人工界面提交，不是 LLM 工具参数或普通聊天消息."""

    decision: Literal["confirm", "cancel"]
    interrupt_id: str = Field(min_length=1, max_length=128)
    review_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PendingActionResponse(BaseResponse):
    """查询当前会话仍等待人工操作的复核卡片."""

    pending_action: HoldingImportReview | None = None
