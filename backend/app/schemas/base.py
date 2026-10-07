"""所有端点共用的响应基类 schema."""

from uuid import UUID, uuid4

from asgi_correlation_id import correlation_id
from pydantic import BaseModel, Field


def _get_request_id() -> UUID:
    """取当前请求的 correlation ID，拿不到就现生成一个 UUID 兜底."""
    value = correlation_id.get()
    return UUID(value) if value else uuid4()


class BaseResponse(BaseModel):
    """所有端点响应都继承的基类模型.

    request_id 由 CorrelationIdMiddleware 的 ContextVar 自动填好——
    端点不需要自己显式传。
    """

    request_id: UUID = Field(default_factory=_get_request_id, description="Unique identifier for this request")


def clean_required_text(value: str | None) -> str | None:
    """去掉用户文本的首尾空白，trim 后为空则拒绝.

    光靠 `min_length=1` 会放过 "   "，这类值落库后就渲染成一行没有名字的记录。
    None 原样返回，PATCH 请求体里它依旧表示“这个字段不动”。
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise ValueError("value must not be blank")
    return text
