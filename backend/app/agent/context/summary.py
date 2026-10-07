"""ConversationSummary：已完成旧 Turn 的批量压缩（spec 19-32）.

只在 `usage_ratio ≥ 阈值` 时由 Batch Compaction 调用一次 LLM；
Summary 失败时不得删除旧 Turn——由调用方（manager）保证。
存储：第一版保存在 ContextManager 的进程内字典（按 thread 键控），
不新增数据库表；重启丢失后会在下次达到阈值时重新压缩。
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.context.models import CompactionResult, ConversationSummary, ConversationTurn
from app.agent.prompts import load_prompt_file
from app.core.logging import logger

_SUMMARY_PROMPT = load_prompt_file("conversation_summary.md")

# 单条消息在摘要输入中的截断长度（工具结果/长回答只保留开头）
_PER_MESSAGE_CLIP = 400


class ConversationSummaryManager:
    """批量压缩管理器：旧 Summary + 一批旧 Turn → 新 Summary."""

    def __init__(self, summarizer=None) -> None:
        """可注入自定义 summarizer（测试用）；默认走 llm_service（无工具的临时实例）."""
        self._summarizer = summarizer

    async def compact(
        self,
        *,
        previous_summary: ConversationSummary | None,
        turns: list[ConversationTurn],
    ) -> CompactionResult:
        """把一批旧 Turn 压缩进摘要.

        Raises:
            Exception: LLM 调用失败时向上抛出——调用方必须保证不删除
                原 Turn、不做 Epoch rollover。
        """
        if not turns and previous_summary is None:
            raise ValueError("compaction 需要至少一个待压缩对象")

        previous_block = previous_summary.content if previous_summary else "（无）"
        turns_block = "\n\n".join(self._render_turn(turn) for turn in turns)
        messages = [
            SystemMessage(content=_SUMMARY_PROMPT),
            HumanMessage(
                content=f"# 既有摘要（v{previous_summary.version if previous_summary else 0}）\n"
                f"{previous_block}\n\n# 待压缩的对话轮次\n{turns_block}\n\n"
                "请输出更新后的摘要。"
            ),
        ]

        summarizer = self._summarizer or self._default_summarize
        content = (await summarizer(messages)).strip()

        previous_version = previous_summary.version if previous_summary else 0
        covered = previous_summary.covered_turn_count + len(turns) if previous_summary else len(turns)
        summary = ConversationSummary(
            content=content,
            version=previous_version + 1,
            covered_turn_count=covered,
            covered_until_turn_id=turns[-1].turn_id,
            created_at=previous_summary.created_at if previous_summary else None,
            updated_at=None,
        )
        logger.info(
            "conversation_summary_compacted",
            summary_version=summary.version,
            covered_turn_count=summary.covered_turn_count,
            compacted_turn_count=len(turns),
        )

        return CompactionResult(summary=summary, compacted_turn_count=len(turns), remaining_turn_count=0)

    async def _default_summarize(self, messages) -> str:
        """默认摘要执行器：走 llm_service 的一次性临时实例（不带工具绑定）."""
        from app.services.llm import llm_service

        response = await llm_service.call(messages)
        return str(response.content)

    async def merge_segments(self, segments: list[ConversationSummary]) -> CompactionResult:
        """把最旧的若干摘要段合并成一段（低频；输入为各段全文）.

        合并是分段方案中唯一的重写点：输入携带各段全文，信息不经过
        多代有损压缩。覆盖的 Turn 总数不变。
        """
        if len(segments) < 2:
            raise ValueError("合并至少需要两个摘要段")

        previous_version = max(segment.version for segment in segments)
        separator = chr(10) * 2
        blocks = separator.join(f"# 摘要段（v{segment.version}）{chr(10)}{segment.content}" for segment in segments)
        tail_instruction = "请把以上摘要段合并为一段，保留所有仍然有效的信息，不要遗漏。"
        messages = [
            SystemMessage(content=_SUMMARY_PROMPT),
            HumanMessage(content=f"# 待合并的摘要段{chr(10)}{blocks}{chr(10)}{tail_instruction}"),
        ]

        summarizer = self._summarizer or self._default_summarize
        content = (await summarizer(messages)).strip()

        summary = ConversationSummary(
            content=content,
            version=previous_version + 1,
            covered_turn_count=sum(segment.covered_turn_count for segment in segments),
            covered_until_turn_id=segments[-1].covered_until_turn_id,
            created_at=None,
        )
        logger.info(
            "summary_segments_merged",
            merged_count=len(segments),
            new_version=summary.version,
        )
        return CompactionResult(summary=summary, compacted_turn_count=0, remaining_turn_count=0)

    @staticmethod
    def _render_turn(turn: ConversationTurn) -> str:
        """把一个 Turn 渲染成摘要输入文本（工具消息只留名字与开头）."""
        lines = [f"用户：{str(turn.user_message.content)[:_PER_MESSAGE_CLIP]}"]
        for message in turn.following_messages:
            message_type = getattr(message, "type", None)
            if message_type == "ai":
                text = str(message.content).strip()
                if text:
                    lines.append(f"助手：{text[:_PER_MESSAGE_CLIP]}")
            elif message_type == "tool":
                lines.append(f"工具[{message.name}]：{str(message.content)[:120]}")
        return "\n".join(lines)
