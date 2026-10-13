"""供网页和移动端共用的 Agent 图片导入与人工复核协议."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.base import BaseResponse
from app.schemas.fund_selection import FundSelectionAction
from app.schemas.agent_resume import AgentRunContinuation
from app.schemas.human_question import HumanQuestionAction
from app.schemas.holding_import import ImportItemOut

ImportId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class HoldingImportReview(BaseModel):
    """结构化 HITL 卡片，图 checkpoint 保存它，客户端刷新可恢复."""

    kind: Literal["holding_import_review"] = "holding_import_review"
    interrupt_id: str = ""
    import_id: ImportId
    account_id: int
    account_name: str = ""
    image_count: int
    review_digest: str
    items: list[ImportItemOut]
    notice: str = "确认后按基金覆盖此账户的持仓快照并记录调整流水；未出现在截图中的其他持仓不会删除。"


class HoldingImportDecision(BaseModel):
    """仅由人工界面提交，不是 LLM 工具参数或普通聊天消息."""

    decision: Literal["confirm", "cancel"]
    interrupt_id: str = Field(min_length=1, max_length=128)
    review_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class HoldingImportProcessing(BaseModel):
    """子图等待后台识别；客户端可刷新或断线后恢复，不调用主图 LLM."""

    kind: Literal["holding_import_processing"] = "holding_import_processing"
    interrupt_id: str = ""
    import_id: ImportId
    notice: str = "正在识别持仓截图，完成后继续选择账户和人工复核。"


class HoldingAccountOption(BaseModel):
    """仅列出认证用户自己的目标账户."""

    id: int
    name: str


class HoldingImportAccountSelection(BaseModel):
    """识别完成但未指定目标账户，等待用户选择，不猜测第一个账户."""

    kind: Literal["holding_import_account"] = "holding_import_account"
    interrupt_id: str = ""
    import_id: ImportId
    accounts: list[HoldingAccountOption]
    notice: str = "截图已识别，请选择要同步到的持仓账户，再核对识别结果。"


HoldingImportAction = Annotated[
    HoldingImportReview | HoldingImportProcessing | HoldingImportAccountSelection,
    Field(discriminator="kind"),
]


class HoldingImportContinueRequest(BaseModel):
    """只恢复真实中断，不能直接确认持仓."""

    interrupt_id: str = Field(min_length=1, max_length=128)


class HoldingImportAccountDecision(HoldingImportContinueRequest):
    """人工目标选择只更新导入草稿，不写入正式持仓."""

    account_id: int = Field(gt=0)


AgentPendingAction = Annotated[
    HoldingImportReview
    | HoldingImportProcessing
    | HoldingImportAccountSelection
    | FundSelectionAction
    | HumanQuestionAction,
    Field(discriminator="kind"),
]


class PendingActionResponse(BaseResponse):
    """查询当前会话仍等待人工操作的复核卡片."""

    pending_action: AgentPendingAction | None = None
    continuation: AgentRunContinuation | None = None
