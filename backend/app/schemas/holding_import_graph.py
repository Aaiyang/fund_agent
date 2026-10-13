"""持仓子图共享消息和初始输入；确认账户与人工决策保持批次私有."""

from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from app.schemas.agent_import import HoldingImportAction, ImportId


class HoldingImportToolArgs(BaseModel):
    """模型只可提供上传批次号，身份和草稿内容不接受模型输入."""

    model_config = ConfigDict(extra="forbid")
    import_id: ImportId


class HoldingImportCall(BaseModel):
    """需要在中断前持久化的原始工具调用关联信息."""

    call_id: str
    name: Literal["get_holding_import", "request_holding_import_confirmation"]
    import_id: ImportId


class HoldingImportContinueValue(BaseModel):
    """识别阶段恢复，仅携带当前批次引用."""

    model_config = ConfigDict(extra="forbid")
    import_id: ImportId
    action: Literal["continue"]


class HoldingImportAccountValue(BaseModel):
    """选择账户阶段恢复，不允许把布尔值或字符串当成账户ID."""

    model_config = ConfigDict(extra="forbid")
    import_id: ImportId
    account_id: int = Field(strict=True, gt=0)


class HoldingImportDecisionValue(BaseModel):
    """人工接口返回的决策回执，正式结果仍需核验数据库."""

    model_config = ConfigDict(extra="forbid")
    import_id: ImportId
    decision: Literal["confirm", "cancel"]
    applied: int = Field(default=0, strict=True, ge=0)
    skipped: int = Field(default=0, strict=True, ge=0)


HoldingImportResumeValue = HoldingImportContinueValue | HoldingImportAccountValue | HoldingImportDecisionValue
_RESUME_VALUE = TypeAdapter(HoldingImportResumeValue)


class HoldingImportGraphState(BaseModel):
    """初始输入保留旧字段名以兼容检查点；处理中确认值不回写初始输入."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    holding_import_ids: list[str] = Field(default_factory=list)
    holding_account_id: int | None = None
    holding_instruction: str = ""
    resolved_account_id: int | None = None
    resolved_import_id: ImportId | None = None
    active_call: HoldingImportCall | None = None
    review: HoldingImportAction | None = None
    decision: HoldingImportResumeValue | None = None

    @field_validator("decision", mode="before")
    @classmethod
    def validate_resume_value(cls, value: object) -> HoldingImportResumeValue | None:
        """兼容旧检查点字典；无效回复不获得权限，交回原阶段等待."""
        if value is None:
            return None
        try:
            return _RESUME_VALUE.validate_python(value)
        except ValidationError:
            return None
