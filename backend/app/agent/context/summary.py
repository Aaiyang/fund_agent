"""只压缩独立的已结束轮次；来源范围可校验，LLM 失败时不推进水位线."""

import json
from collections.abc import Awaitable, Callable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.constants import TAG_NOSTREAM

from app.agent.context.budget import token_estimator
from app.agent.context.cache_policy import cache_policy
from app.agent.context.models import CompactionResult, ConversationSummary, ConversationTurn
from app.agent.prompts import load_prompt_file
from app.core.logging import logger
from app.utils.clock import utc_now

_SUMMARY_PROMPT = load_prompt_file("conversation_summary.md")
Summarizer = Callable[[list[BaseMessage]], Awaitable[str]]


def turn_hash(turn: ConversationTurn) -> str:
    """消息 ID 和完整原文共同确定摘要来源，不依赖可变的 token 估算."""
    return cache_policy.fingerprint(
        [
            {
                "id": getattr(message, "id", None),
                "type": getattr(message, "type", None),
                "content": message.content,
                "tool_calls": getattr(message, "tool_calls", None),
                "tool_call_id": getattr(message, "tool_call_id", None),
                "name": getattr(message, "name", None),
            }
            for message in [turn.user_message, *turn.following_messages]
        ]
    )


class ConversationSummaryManager:
    """按输入 token 预算分批压缩；最近原文由调用方保留."""

    def __init__(self, summarizer: Summarizer | None = None) -> None:
        """测试可注入摘要器；生产调用继承认证用户的模型与追踪."""
        self._summarizer = summarizer
        self.llm_call: Callable[..., Awaitable[BaseMessage]] | None = None

    @staticmethod
    def _messages(turns: list[ConversationTurn]) -> list[BaseMessage]:
        body = "\n\n".join(ConversationSummaryManager._render_turn(turn) for turn in turns)
        return [
            SystemMessage(content=_SUMMARY_PROMPT),
            HumanMessage(content=f"# 待压缩的独立对话轮次\n{body}\n\n只输出这一批轮次的事实摘要。"),
        ]

    async def compact(
        self,
        *,
        turns: list[ConversationTurn],
        source_start: int,
        version: int,
        input_token_limit: int,
        output_token_limit: int,
    ) -> CompactionResult:
        """选择预算内的连续前缀，完整发送原文，禁止按字符静默截断."""
        batch: list[ConversationTurn] = []
        for turn in turns:
            candidate = [*batch, turn]
            if token_estimator.count_messages(self._messages(candidate)) > input_token_limit:
                break
            batch = candidate
        if not batch:
            raise ValueError("a complete turn cannot fit the summary input budget")
        content = await self._summarize(self._messages(batch), output_token_limit)
        hashes = [turn_hash(turn) for turn in batch]
        now = utc_now()
        summary = ConversationSummary(
            content=content,
            version=version,
            covered_turn_count=len(batch),
            source_start=source_start,
            source_end=source_start + len(batch),
            source_turn_hashes=hashes,
            source_hash=cache_policy.fingerprint(hashes),
            covered_from_turn_id=batch[0].turn_id,
            covered_until_turn_id=batch[-1].turn_id,
            created_at=now,
            updated_at=now,
        )
        logger.info("conversation_summary_compacted", summary_version=version, compacted_turn_count=len(batch))
        return CompactionResult(
            summary=summary, compacted_turn_count=len(batch), remaining_turn_count=len(turns) - len(batch)
        )

    async def _summarize(self, messages: list[BaseMessage], output_token_limit: int) -> str:
        if self._summarizer:
            content = await self._summarizer(messages)
        else:
            # max_tokens 进入一次性模型路径，不绑定工具，不改变聊天模型降级位置。
            if self.llm_call is None:
                raise RuntimeError("summary LLM dependency is not configured")
            response = await self.llm_call(
                messages, max_tokens=output_token_limit, tags=[TAG_NOSTREAM, "context_summary"]
            )
            metadata = response.response_metadata or {}
            if (
                getattr(response, "tool_calls", None)
                or metadata.get("finish_reason") in {"tool_calls", "length", "content_filter"}
                or response.additional_kwargs.get("refusal")
            ):
                raise ValueError("summary response is incomplete or refused")
            if isinstance(response.content, str):
                content = response.content
            else:
                content = "".join(
                    block if isinstance(block, str) else block.get("text", "")
                    for block in response.content
                    if isinstance(block, str) or block.get("type") == "text"
                )
        content = content.strip()
        if not content or token_estimator.count_text(content) > output_token_limit:
            raise ValueError("empty or oversized summary response")
        return content

    async def merge_segments(
        self, segments: list[ConversationSummary], *, version: int, input_token_limit: int, output_token_limit: int
    ) -> CompactionResult:
        """只合并相邻、互不重叠的段；全文输入，来源范围和轮数保持不变."""
        if len(segments) < 2:
            raise ValueError("at least two segments are required")
        for left, right in zip(segments, segments[1:], strict=False):
            if left.source_end != right.source_start:
                raise ValueError("summary sources are not adjacent")
        blocks = "\n\n".join(segment.content for segment in segments)
        messages: list[BaseMessage] = [
            SystemMessage(content=_SUMMARY_PROMPT),
            HumanMessage(content=f"# 待合并的相邻摘要段\n{blocks}\n\n合并为一段事实摘要，保留有效约束与结论。"),
        ]
        if token_estimator.count_messages(messages) > input_token_limit:
            raise ValueError("summary merge input exceeds budget")
        hashes = [source for segment in segments for source in segment.source_turn_hashes]
        summary = ConversationSummary(
            content=await self._summarize(messages, output_token_limit),
            version=version,
            covered_turn_count=sum(segment.covered_turn_count for segment in segments),
            source_start=segments[0].source_start,
            source_end=segments[-1].source_end,
            source_turn_hashes=hashes,
            source_hash=cache_policy.fingerprint(hashes),
            covered_from_turn_id=segments[0].covered_from_turn_id,
            covered_until_turn_id=segments[-1].covered_until_turn_id,
            created_at=segments[0].created_at,
            updated_at=utc_now(),
        )
        return CompactionResult(summary=summary, compacted_turn_count=0, remaining_turn_count=0)

    @staticmethod
    def _render_turn(turn: ConversationTurn) -> str:
        """保留完整原文与工具参数；分批限制总量而不截掉消息尾部."""
        lines = [f"用户：{turn.user_message.content}"]
        for message in turn.following_messages:
            if getattr(message, "type", None) == "ai":
                if message.content:
                    lines.append(f"助手：{message.content}")
                if getattr(message, "tool_calls", None):
                    lines.append("工具调用：" + json.dumps(message.tool_calls, ensure_ascii=False, sort_keys=True))
            elif getattr(message, "type", None) == "tool":
                lines.append(f"工具[{message.name}]：{message.content}")
        return "\n".join(lines)
