"""所有业务工具适配器共享的辅助函数."""

import functools
from typing import Any

from langgraph.errors import GraphInterrupt

from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import ToolRuntimeError
from app.core.logging import logger


def drop_nones(value: Any) -> Any:
    """递归剔除 None 字段，压缩工具返回体积，让提示词更精简."""
    if isinstance(value, dict):
        return {k: drop_nones(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nones(item) for item in value if item is not None]
    return value


def tool_result(fn):
    """把工具协程的 ToolResult 转成文本，并统一失败处理.

    - ToolRuntimeError（身份缺失等）→ 使用其自带的错误码。
    - 其他任何异常 → 返回 UPSTREAM_ERROR 与安全消息；真实堆栈只留在
      服务端日志，永远到不了 LLM。
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            result = await fn(*args, **kwargs)
        except ToolRuntimeError as e:
            return ToolResult.fail(e.code, e.message).to_text()
        except GraphInterrupt:
            raise
        except Exception:
            logger.exception("tool_execution_failed", tool=fn.__name__)
            return ToolResult.fail(
                "UPSTREAM_ERROR",
                "查询业务数据失败，请稍后重试",
                retryable=True,
            ).to_text()
        if isinstance(result, ToolResult):
            return result.to_text()
        return result

    return wrapper


def validate_fund_code(fund_code: str) -> str:
    """去除空白并校验 6 位基金代码；绝不静默改写.

    Raises:
        ToolRuntimeError: 代码不是 6 位数字时返回 INVALID_ARGUMENT——
            必须让模型自行纠正，而不是工具去猜 "11011" 或
            "005827.OF" 是什么意思（任务书 25）。
    """
    code = fund_code.strip()
    if len(code) != 6 or not code.isdigit():
        raise ToolRuntimeError(
            "INVALID_ARGUMENT",
            f"基金代码必须是 6 位数字，收到：'{fund_code}'",
        )
    return code
