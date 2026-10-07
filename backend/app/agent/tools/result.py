"""面向 LLM 的业务工具统一结果信封.

每个业务工具都返回渲染成文本的 ``ToolResult``，无论背后是哪个 Service，
模型看到的成功/失败结构完全一致。异常堆栈、SQL 与密钥永远到不了这一层——
调用方只会把安全的错误信息放进 ``ToolError``。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.utils.clock import utc_now


class ToolError(BaseModel):
    """机器可读的失败信息，可以安全展示给 LLM."""

    code: str
    message: str
    retryable: bool = False


class ToolResult(BaseModel):
    """单次工具执行的结果信封.

    ``as_of`` 是数据实际描述的业务日期（ISO 字符串——Service 对净值/持仓
    返回 ``date``、对行情返回 ``datetime``，统一成字符串避免伪造出
    不存在的精度）。
    """

    success: bool
    data: Any | None = None
    source: str | None = None
    as_of: str | None = None
    fetched_at: datetime = Field(default_factory=utc_now)
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: ToolError | None = None
    trace_id: str | None = None

    @classmethod
    def ok(
        cls,
        data: Any,
        *,
        source: str | None = None,
        as_of: str | None = None,
        stale: bool = False,
        warnings: list[str] | None = None,
    ) -> "ToolResult":
        """构建携带 ``data`` 的成功结果."""
        return cls(
            success=True,
            data=data,
            source=source,
            as_of=as_of,
            stale=stale,
            warnings=warnings or [],
        )

    @classmethod
    def fail(
        cls,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> "ToolResult":
        """用安全的错误码与消息构建失败结果."""
        return cls(success=False, error=ToolError(code=code, message=message, retryable=retryable))

    def to_text(self) -> str:
        """渲染成 ToolMessage 文本：紧凑 JSON 数据 + 元信息尾注."""
        if not self.success:
            error = self.error
            retry = " retryable=true" if error and error.retryable else ""
            return f"[TOOL_ERROR] {error.code if error else 'INTERNAL_ERROR'}: {error.message if error else ''}{retry}"
        parts = ["[TOOL_OK]"]
        if self.data is not None:
            parts.append(self.data if isinstance(self.data, str) else json_compact(self.data))
        meta = []
        if self.as_of:
            meta.append(f"as_of={self.as_of}")
        if self.source:
            meta.append(f"source={self.source}")
        if self.stale:
            meta.append("stale=true — 数据可能不是最新的，回答时需要说明")
        for warning in self.warnings:
            meta.append(f"note: {warning}")
        if meta:
            parts.append("; ".join(meta))
        return "\n".join(parts)


def json_compact(data: Any) -> str:
    """序列化工具数据并剔除 None 字段，让提示词更精简."""
    import json

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
