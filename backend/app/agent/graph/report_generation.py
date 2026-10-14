"""在同一条流内有界续写报告，保留证据、回调与已经展示的正文前缀."""

import asyncio
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages.ai import UsageMetadata, add_usage

from app.agent.context import extract_text_content, process_llm_response
from app.core.config import settings
from app.core.logging import logger
from app.services.llm.timeouts import LLMResponseInterrupted


async def generate_research_report(
    messages: list[BaseMessage], call: Callable[..., Awaitable[BaseMessage]]
) -> AIMessage:
    """长度截断只追加剩余正文；仍未完成则保留检查点供继续，不提交残缺报告."""
    requests = list(messages)
    content = ""
    usage: UsageMetadata | None = None
    deadline = asyncio.timeout(settings.LLM_TOTAL_TIMEOUT)
    try:
        async with deadline:
            for continuation in range(settings.RESEARCH_REPORT_MAX_CONTINUATIONS + 1):
                response = process_llm_response(
                    await call(requests, max_tokens=settings.RESEARCH_REPORT_MAX_TOKENS, report_mode=True)
                )
                if not isinstance(response, AIMessage) or response.tool_calls:
                    raise ValueError("research report requires assistant text without tools")
                content += extract_text_content(response.content)
                usage = add_usage(usage, response.usage_metadata)
                if response.response_metadata.get("finish_reason") != "length":
                    if not content.strip():
                        raise LLMResponseInterrupted("empty")
                    return response.model_copy(
                        update={
                            "content": content,
                            "usage_metadata": usage,
                            "response_metadata": {
                                **response.response_metadata,
                                "report_continuations": continuation,
                            },
                        }
                    )
                if continuation == settings.RESEARCH_REPORT_MAX_CONTINUATIONS:
                    raise LLMResponseInterrupted("length")
                logger.info("research_report_continuing", continuation=continuation + 1, output_chars=len(content))
                # 保留同一份可信证据；追加指令仅用于接续，不重新路由或查询工具。
                requests = [
                    *messages,
                    *([AIMessage(content=content)] if content else []),
                    HumanMessage(
                        content=(
                            "上一次报告因输出长度上限而中断。严格沿用上述研究要求、数据与来源，"
                            "从已输出正文的断点接着写，直到完成所有剩余部分。"
                            "已输出内容已展示，请勿重复、改写、重新开头或说明续写过程；"
                            "若断点位于句子、表格或代码围栏内，请直接接续原格式。"
                            if content
                            else "上一次调用耗尽输出额度且没有报告正文。请直接按上述证据与要求输出完整报告。"
                        )
                    ),
                ]
    except TimeoutError:
        if not deadline.expired():
            raise
        raise LLMResponseInterrupted("total") from None
    raise LLMResponseInterrupted("length")
