"""按有意义的流式进度管理超时，不把心跳当成答案或重放已输出的回答."""

import asyncio
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, override

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from openai import APITimeoutError


class LLMStartTimeout(APITimeoutError):
    """尚无输出时的应用级等待超时，可切换模型但不在原模型耗尽重试预算."""

    def __init__(self) -> None:
        """创建不携带用户请求内容或密钥的 SDK 兼容异常."""
        super().__init__(request=httpx.Request("POST", "https://llm.invalid/"))


class LLMResponseInterrupted(RuntimeError):
    """已有部分流式结果时中止，禁止重试或降级后混入第二份回答."""

    def __init__(self, reason: str) -> None:
        """区分断流与总时限，给客户端可理解的未完成提示."""
        self.reason = reason
        message = {
            "idle": "模型输出长时间没有进展，回答未完成；已显示的部分内容可保留，请重试补充未完成部分。",
            "upstream": "模型连接在生成过程中中断，回答未完成；请重试补充未完成部分。",
            "total": "模型调用达到总等待上限，回答未完成；请缩小分析范围或重试补充未完成部分。",
            "length": "报告达到输出长度上限，尚未完整生成；已显示的内容已保留，请继续原任务。",
            "empty": "模型未返回报告正文，研究尚未完成，请继续原任务。",
        }[reason]
        super().__init__(message)


class LLMContractViolation(RuntimeError):
    """模型确实回话了，但内容不符合给定的结构化契约.

    与"连接中断""达到长度上限"分开：那两类是传输问题，这一类是契约问题——以前它被
    笼统算成失败原因、又被节点吞成"角色未完成"，于是界面上分不清"模型没做"和
    "做了但字段不合"。带上 field_errors，调用方可以把它回喂给模型改一次。
    """

    def __init__(self, model_name: str, field_errors: str) -> None:
        """记录契约所属模型与 pydantic 的字段级错误文本."""
        self.model_name = model_name
        self.field_errors = field_errors
        super().__init__(f"{model_name} 的输出不符合结构契约：{field_errors}")

    @property
    def reason(self) -> str:
        """与其它 LLM 异常保持一致的 reason 口径."""
        return "contract"


class LLMCallProgress(BaseCallbackHandler):
    """单次调用私有的同步回调，保留 LangGraph/Langfuse 的原有回调链."""

    run_inline = True

    def __init__(self, idle_timeout: float, on_text: Callable[[str], None] | None = None) -> None:
        """记录进度及耗时，不保存任何回答正文.

        ``on_text`` 存在实例属性 ``text_observer`` 上而不是 ``on_text``：后者是
        ``BaseCallbackHandler`` 自己的回调方法名，同名会盖掉继承来的签名。
        """
        self.idle_timeout = idle_timeout
        self.text_observer = on_text
        self.started_at = time.monotonic()
        self.first_progress_at: float | None = None
        self.last_progress_at: float | None = None
        self.progress_chunks = 0
        self.output_chars = 0
        # 结构化输出（include_raw）的 token 与 finish_reason 只能从 raw 那份拿，
        # 记在这里，成功日志才不会全是 None。
        self.structured_usage: dict[str, Any] = {}
        self.structured_finish_reason: str | None = None
        self.attempts = 0
        self.models_tried: list[str] = []
        self.deadline: asyncio.Timeout | None = None

    @override
    def on_llm_new_token(self, token: str, *, chunk: Any = None, **kwargs: Any) -> None:
        """正文、推理和工具参数都算进度；空帧不延长等待时间."""
        message = getattr(chunk, "message", None)
        additional = getattr(message, "additional_kwargs", {}) or {}
        metadata = getattr(message, "response_metadata", {}) or {}
        progress = (
            token
            or getattr(message, "tool_call_chunks", None)
            or additional.get("reasoning_content")
            or metadata.get("fund_reasoning_chars")
        )
        if not progress:
            return
        if self.text_observer is not None:
            # 思考片段优先：正文在结构化输出里是零散的 JSON，界面要看的正是"想到哪了"。
            fragment = additional.get("reasoning_content") or (token if isinstance(token, str) else "")
            if fragment:
                self.text_observer(fragment)
        now = time.monotonic()
        self.first_progress_at = self.first_progress_at or now
        self.last_progress_at = now
        self.progress_chunks += 1
        # LangChain v1 也可把结构化内容块作为 token 传入。
        self.output_chars += len(token) if isinstance(token, str) else len(getattr(chunk, "text", ""))
        if self.deadline is not None and not self.deadline.expired():
            self.deadline.reschedule(asyncio.get_running_loop().time() + self.idle_timeout)

    def diagnostics(self) -> dict[str, Any]:
        """提供超时后仍可记录的指标，避免只留下失败栈而没有流式证据."""
        now = time.monotonic()
        return {
            "elapsed_seconds": round(now - self.started_at, 3),
            "first_progress_seconds": round(self.first_progress_at - self.started_at, 3)
            if self.first_progress_at
            else None,
            "last_progress_age_seconds": round(now - self.last_progress_at, 3) if self.last_progress_at else None,
            "progress_chunks": self.progress_chunks,
            "output_chars": self.output_chars,
            "attempt_count": self.attempts,
            "models_tried": self.models_tried,
        }


call_progress: ContextVar[LLMCallProgress | None] = ContextVar("llm_call_progress", default=None)
