"""Token 预算、工具观测去重与裁剪机制.

职责边界：本模块只做与业务无关的量化管理——去重、单条硬上限、
完整 Turn 选择、超预算淘汰。基金持仓/净值/行情等业务字段的裁剪
属于 `app/agent/tools/` 层的职责，这里不理解任何业务语义。
"""

import hashlib
import json

import tiktoken
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.agent.context.models import ContextEnvelope, ConversationTurn, ContextInvariantError
from app.core.config import settings

# 单条 ToolMessage 的 token 硬上限：正常工具输出应远低于该值，
# 超限说明某个工具忘记做输出控制——这里只做异常兜底截断。
MAX_SINGLE_TOOL_MESSAGE_TOKENS = 4000

_DEDUP_STUB = "[已去重：与后一次相同调用的结果一致]"


class TokenEstimator:
    """基于 tiktoken 的本地 token 估算（复用旧实现，不新建第二套 tokenizer）.

    口径统一约定：全项目所有 token 计数都归结为 count_message（单条 =
    4 开销 + 内容）之和，不存在任何"按轮附加费"——这样无论按轮分组
    求和还是整表一次计数，同一份消息列表必然得到同一个数字。
    """

    def __init__(self) -> None:
        """初始化编码器：优先匹配当前模型，失败回退 cl100k_base."""
        try:
            self._encoding = tiktoken.encoding_for_model(settings.DEFAULT_LLM_MODEL)
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")

    def count_text(self, text: str) -> int:
        """统计一段文本的 token 数."""
        return len(self._encoding.encode(text))

    def truncate_text(self, text: str, max_tokens: int) -> str:
        """按 token 截取前缀，丢弃边界上未完成的 UTF-8 字符."""
        tokens = self._encoding.encode(text)[: max(0, max_tokens)]
        clipped = self._encoding.decode_bytes(tokens).decode("utf-8", errors="ignore")
        while tokens and self.count_text(clipped) > max_tokens:
            tokens.pop()
            clipped = self._encoding.decode_bytes(tokens).decode("utf-8", errors="ignore")
        return clipped

    def count_message(self, message) -> int:
        """统计单条消息：固定 4 开销 + 内容。全局唯一的计价单元."""
        total = 4  # 每条消息的角色/名字自带固定开销
        if isinstance(message, dict):
            for value in message.values():
                if isinstance(value, str):
                    total += self.count_text(value)
        else:
            content = getattr(message, "content", "")
            if isinstance(content, str):
                total += self.count_text(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        total += self.count_text(block)
                    elif isinstance(block, dict) and "text" in block:
                        total += self.count_text(block["text"])
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                total += self.count_text(json.dumps(tool_calls, ensure_ascii=False, sort_keys=True))
            for attribute in ("name", "tool_call_id"):
                value = getattr(message, attribute, None)
                if value:
                    total += self.count_text(str(value))
        return total

    def count_tool_schemas(self, schemas: list | None) -> int:
        """工具定义也占输入窗口；兼容模型 tokenizer 未知时仍为本地估算."""
        return self.count_text(json.dumps(schemas, ensure_ascii=False, sort_keys=True)) if schemas else 0

    def count_messages(self, messages) -> int:
        """统计消息列表：逐条之和（与任何分组方式求和的结果完全一致）."""
        return sum(self.count_message(m) for m in messages)


token_estimator = TokenEstimator()


def _fingerprint(tool_name: str, content: str) -> str:
    """工具名 + 结果内容的去重指纹."""
    return hashlib.sha1(f"{tool_name}::{content}".encode("utf-8")).hexdigest()


def dedup_tool_trace(messages: list) -> tuple[list, int]:
    """对当前轮的工具结果去重：相同（工具名 + 结果指纹）只保留最后一次.

    采用"内容替换为占位符"而不是删除消息——保证 AI ToolCall 与
    ToolMessage 的配对关系不被破坏（spec 12/18）。返回（新列表, 去重条数）。
    """
    fingerprint_at: dict[str, int] = {}
    stub_positions: set[int] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        key = _fingerprint(message.name or "", str(message.content))
        if key in fingerprint_at:
            stub_positions.add(index)
        fingerprint_at[key] = index

    if not stub_positions:
        return messages, 0

    result: list = []
    removed = 0
    for index, message in enumerate(messages):
        if index in stub_positions:
            removed += 1
            result.append(
                ToolMessage(
                    content=_DEDUP_STUB,
                    name=message.name,
                    tool_call_id=message.tool_call_id,
                )
            )
        else:
            result.append(message)
    return result, removed


def hard_limit_tool_trace(
    messages: list,
    estimator: TokenEstimator,
    limit: int = MAX_SINGLE_TOOL_MESSAGE_TOKENS,
) -> tuple[list, int]:
    """单条 ToolMessage 超过硬上限时的兜底截断（异常保险，非正常压缩）.

    返回（新列表, 被截断的条数）。
    """
    if limit <= 0:
        raise ValueError("tool_message_limit must be positive")
    result: list = []
    compacted = 0
    for message in messages:
        if isinstance(message, ToolMessage) and estimator.count_text(str(message.content)) > limit:
            compacted += 1
            marker = f"\n[TRUNCATED: 单条工具结果超出 {limit} token 上限，已被截断]"
            if estimator.count_text(marker) > limit:
                marker = estimator.truncate_text("[TRUNCATED]", limit)
            available = max(0, limit - estimator.count_text(marker))
            clipped = estimator.truncate_text(str(message.content), available) + marker
            while estimator.count_text(clipped) > limit and available > 0:
                available -= max(1, estimator.count_text(clipped) - limit)
                clipped = estimator.truncate_text(str(message.content), available) + marker
            result.append(message.model_copy(update={"content": clipped}))
        else:
            result.append(message)
    return result, compacted


def tool_trace_blocks(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
    """把一次 AI 并行调用及其所有结果作为不可拆分的预算单元.

    只分组，不补造或删除非法消息；原始轨迹的问题仍由校验器拒绝。
    """
    blocks: list[list[BaseMessage]] = []
    for message in messages:
        if (
            isinstance(message, ToolMessage)
            and blocks
            and isinstance(blocks[-1][0], AIMessage)
            and any(call["id"] == message.tool_call_id for call in blocks[-1][0].tool_calls)
        ):
            blocks[-1].append(message)
        else:
            blocks.append([message])
    return blocks


def select_recent_turns(
    turns: list[ConversationTurn],
    estimator: TokenEstimator,
    remaining_tokens: int,
) -> tuple[list[ConversationTurn], int]:
    """从最新到最旧选择完整 Turn，装不下就停止（保持时间连续，不产生半截轮次）.

    返回（按时间顺序排列的选中 Turn, 被丢弃的最老 Turn 数量）。
    """
    selected: list[ConversationTurn] = []
    used = 0
    for turn in reversed(turns):
        cost = turn.estimated_tokens or estimator.count_messages([turn.user_message, *turn.following_messages])
        if used + cost > remaining_tokens:
            break
        selected.insert(0, turn)
        used += cost
    dropped = len(turns) - len(selected)
    return selected, dropped


def fit_context(
    envelope: ContextEnvelope,
    estimator: TokenEstimator,
    max_tokens: int,
    fixed_cost: int,
    tool_message_limit: int = MAX_SINGLE_TOOL_MESSAGE_TOKENS,
) -> tuple[ContextEnvelope, int, int, int]:
    """按优先级把信封装配进预算：去重 → 硬上限 → 当前轨迹 → 最近 Turn.

    优先级（spec 15）：P0 当前用户提问（永不删除）→ P1 当前工具轨迹 →
    P2 最近完整 Turn。当前轨迹自身超预算时抛 CONTEXT_BUDGET_EXCEEDED。

    Returns:
        (信封, 去重条数, 截断条数, 丢弃 Turn 数)。
    """
    messages, removed = dedup_tool_trace(envelope.current_turn_messages)
    messages, compacted = hard_limit_tool_trace(messages, estimator, tool_message_limit)

    system_and_trace = fixed_cost + estimator.count_messages(messages)

    if system_and_trace > max_tokens:
        # 保留当前提问 + 最近最多两次完整交互。一次调用可能有多个
        # ToolMessage，不能按消息条数截尾；预算不足时再整组淘汰较早交互。
        blocks = tool_trace_blocks(messages[1:])
        keep = min(2, len(blocks))
        candidate = [messages[0], *(message for block in blocks[-keep:] for message in block)] if keep else messages
        while keep > 1 and fixed_cost + estimator.count_messages(candidate) > max_tokens:
            keep -= 1
            candidate = [messages[0], *(message for block in blocks[-keep:] for message in block)]
        if len(candidate) < len(messages):
            messages = candidate
            compacted += 1
            system_and_trace = fixed_cost + estimator.count_messages(messages)

    if system_and_trace > max_tokens:
        raise ContextInvariantError(
            "CONTEXT_BUDGET_EXCEEDED",
            f"当前轮工具轨迹加系统提示词已超过预算（{system_and_trace} > {max_tokens}）",
        )

    remaining = max_tokens - system_and_trace
    recent_turns, dropped = select_recent_turns(envelope.recent_turns, estimator, remaining)

    envelope.current_turn_messages = messages
    envelope.recent_turns = recent_turns
    return envelope, removed, compacted, dropped


class ContextBudgetManager:
    """按优先级把信封装配进预算（spec 15/16）.

    处理顺序：去重 → 单条硬上限 → 当前轮轨迹 → 从最新到最旧选择完整 Turn。
    当前轮轨迹自身超预算时抛 CONTEXT_BUDGET_EXCEEDED（spec 16 第 8 步）。
    """

    def __init__(
        self,
        estimator: TokenEstimator | None = None,
        max_single_tool_message_tokens: int = MAX_SINGLE_TOOL_MESSAGE_TOKENS,
    ) -> None:
        """注入 token 估算器与单条工具消息硬上限."""
        self.estimator = estimator or token_estimator
        self.max_single = max_single_tool_message_tokens

    def fit(
        self,
        envelope: ContextEnvelope,
        max_tokens: int,
        fixed_cost: int,
        tool_message_limit: int = MAX_SINGLE_TOOL_MESSAGE_TOKENS,
    ) -> tuple[ContextEnvelope, int, int, int]:
        """执行预算装配，返回（信封, 去重条数, 截断条数, 丢弃 Turn 数）.

        fixed_cost = 系统提示词 + Dynamic Tail 等不参与 Turn 淘汰的固定开销。
        """
        return fit_context(envelope, self.estimator, max_tokens, fixed_cost, tool_message_limit)
