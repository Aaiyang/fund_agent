"""可治理语义记忆、增量任务与纠错接口的严格协议."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MemoryKind = Literal["research_preference", "analysis_event"]


class MemoryOperation(BaseModel):
    """提取器只能提出有当前用户原文证据的有限操作."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["upsert", "delete"] = "upsert"
    kind: MemoryKind
    key: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_:.-]+$")
    content: str = Field(default="", max_length=240)
    source_quote: str = Field(min_length=1, max_length=500)
    memory_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def valid_action(self) -> "MemoryOperation":
        """删除必须定位已有条目，新增必须有内容."""
        if self.action == "delete" and not self.memory_id:
            raise ValueError("删除操作必须提供 memory_id")
        if self.action == "upsert" and not self.content:
            raise ValueError("写入操作必须提供 content")
        return self


class MemoryExtraction(BaseModel):
    """单条新增用户消息最多提取五条记忆."""

    model_config = ConfigDict(extra="forbid")
    operations: list[MemoryOperation] = Field(max_length=5)


class MemoryEdit(BaseModel):
    """人工纠错不会重新让模型猜测用户的意思."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1, strict=True)
    content: str = Field(min_length=1, max_length=240)


class MemoryDelete(BaseModel):
    """版本保护的单条删除."""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)


class MemoryClear(BaseModel):
    """版本保护的全量语义记忆清除."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)


class MemorySettingsUpdate(MemoryClear):
    """关闭停止新写入与召回，保留已有内容供用户管理."""

    enabled: bool = Field(strict=True)


class MemorySettingsOut(BaseModel):
    """用户控制开关与检索缓存使用的版本."""

    enabled: bool = True
    revision: int = 0
    generation: int = 0
    globally_enabled: bool


class MemoryItemOut(BaseModel):
    """只返回数据库当前版本，不返回向量里的旧文本."""

    id: str
    kind: MemoryKind
    content: str
    source_quote: str
    source_session_id: str
    source_message_id: str
    version: int
    index_state: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryJobOut(BaseModel):
    """任务观察不暴露完整聊天载荷或底层异常详情."""

    id: str
    kind: str
    status: str
    attempts: int
    error_code: str | None
    source_session_id: str
    source_message_id: str
    created_at: datetime
    updated_at: datetime
