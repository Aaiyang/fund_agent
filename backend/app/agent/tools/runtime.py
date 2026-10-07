"""业务工具的每次调用级运行时上下文.

身份信息永远不来自 LLM：``user_id`` / ``thread_id`` 取自 chatbot.py 根据
已认证请求构建的 LangGraph 调用配置，由 tool_call 节点放入上下文变量，
再在各个工具内部读取。因此工具的输入 Schema 天然不含任何身份参数。
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from asgi_correlation_id import correlation_id


class ToolRuntimeError(Exception):
    """运行时上下文问题，可作为 ToolError 错误码安全透出给 LLM."""

    def __init__(self, code: str, message: str) -> None:
        """携带工具错误码与可安全展示的消息."""
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolRuntimeContext:
    """调用者是谁，以及这次调用属于哪个会话."""

    user_id: int
    thread_id: str
    request_id: str


_CURRENT_RUNTIME: ContextVar[ToolRuntimeContext | None] = ContextVar("tool_runtime", default=None)


def set_tool_runtime(context: ToolRuntimeContext) -> None:
    """为当前异步任务绑定上下文（子任务会继承）."""
    _CURRENT_RUNTIME.set(context)


def get_tool_runtime() -> ToolRuntimeContext:
    """读取已绑定的上下文；工具通过它拿身份，而不是把 user_id 当参数."""
    context = _CURRENT_RUNTIME.get()
    if context is None:
        raise ToolRuntimeError(
            "PERMISSION_DENIED",
            "工具运行时身份缺失，无法确定当前用户",
        )
    return context


def runtime_from_config(config: Any) -> ToolRuntimeContext:
    """从 LangGraph 调用配置构建运行时上下文.

    ``chatbot.py`` 已填好 ``metadata.user_id``（字符串化的整数）与
    ``metadata.session_id``；``configurable.thread_id`` 携带同一个会话 ID
    供 checkpointer 使用。
    """
    metadata = (config or {}).get("metadata") or {}
    configurable = (config or {}).get("configurable") or {}

    raw_user_id = metadata.get("user_id") or configurable.get("user_id")
    if raw_user_id is None:
        raise ToolRuntimeError(
            "PERMISSION_DENIED",
            "调用缺少已认证的用户身份，拒绝执行业务工具",
        )
    try:
        user_id = int(str(raw_user_id))
    except ValueError as e:
        raise ToolRuntimeError(
            "PERMISSION_DENIED",
            "调用缺少已认证的用户身份，拒绝执行业务工具",
        ) from e

    thread_id = str(configurable.get("thread_id") or metadata.get("session_id") or "")
    request_id = correlation_id.get() or ""
    return ToolRuntimeContext(user_id=user_id, thread_id=thread_id, request_id=request_id)
