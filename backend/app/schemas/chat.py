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


class ChatRequest(BaseModel):
    """chat 端点的请求模型.

    Attributes:
        messages: 本次对话的消息列表。
    """

    messages: List[Message] = Field(
        ...,
        description="List of messages in the conversation",
        min_length=1,
    )


class ChatResponse(BaseResponse):
    """chat 端点的响应模型.

    Attributes:
        messages: 本次对话的消息列表。
    """

    messages: List[Message] = Field(..., description="List of messages in the conversation")


class StreamResponse(BaseResponse):
    """流式 chat 端点的响应模型.

    Attributes:
        content: 当前这一段的内容。
        done: 整条流是否已经结束。
    """

    content: str = Field(default="", description="The content of the current chunk")
    done: bool = Field(default=False, description="Whether the stream is complete")


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
