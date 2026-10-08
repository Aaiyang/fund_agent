"""应用的对话相关 schema 定义."""

import re
from typing import (
    List,
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from app.schemas.base import BaseResponse
from app.schemas.agent_import import HoldingImportReview, ImportId


class Message(BaseModel):
    """chat 端点的消息模型.

    Attributes:
        role: 消息发送方角色（user 或 assistant）。
        content: 消息正文。
    """

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"] = Field(..., description="The role of the message sender")
    content: str = Field(..., description="The content of the message", min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """校验消息正文.

        Args:
            v: 待校验的正文

        Returns:
            str: 校验通过的正文

        Raises:
            ValueError: 正文里出现不允许的内容时抛出
        """
        # 拦掉可能有危害的内容
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")

        # 拦掉空字节
        if "\0" in v:
            raise ValueError("Content contains null bytes")

        return v


class ChatInputMessage(BaseModel):
    """客户端只允许提交用户消息，系统指令与模型历史由服务端构建."""

    role: Literal["user"]
    content: str = Field(..., min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """沿用输入正文校验，不允许客户端伪造角色."""
        return Message.validate_content(value)


class ChatRequest(BaseModel):
    """chat 端点的请求模型.

    Attributes:
        messages: 本次对话的消息列表。
    """

    messages: List[ChatInputMessage] = Field(
        ...,
        description="List of messages in the conversation",
        min_length=1,
    )
    holding_import_ids: list[ImportId] = Field(default_factory=list, max_length=5)


class ChatResponse(BaseResponse):
    """chat 端点的响应模型.

    Attributes:
        messages: 本次对话的消息列表。
    """

    messages: List[Message] = Field(..., description="List of messages in the conversation")
    pending_action: HoldingImportReview | None = None


class StreamResponse(BaseResponse):
    """流式 chat 端点的响应模型.

    Attributes:
        content: 当前这一段的内容。
        done: 整条流是否已经结束。
    """

    content: str = Field(default="", description="The content of the current chunk")
    done: bool = Field(default=False, description="Whether the stream is complete")
    pending_action: HoldingImportReview | None = None


class HoldingImportDecisionResponse(ChatResponse):
    """人工操作结果由数据库确定，客户端不依赖模型生成的成功描述."""

    import_id: ImportId
    status: Literal["APPLIED", "CANCELLED"]
    applied: int
    skipped: int


class SessionTitle(BaseModel):
    """会话标题生成所用的结构化输出 schema."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=60,
    )

    @field_validator("title")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = " ".join(v.split()).strip(" \"'`.,:;!?-")
        if not v:
            raise ValueError("empty title after normalization")
        return v
