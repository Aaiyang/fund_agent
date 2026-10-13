"""Agent 上下文组装工具：历史修剪、消息转换与 token 估算."""

from asyncio import Lock
from math import ceil
from typing import Any
from weakref import WeakValueDictionary

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
)
from langchain_core.messages import trim_messages as _trim_messages

from app.agent.context import state_store
from app.agent.context.budget import ContextBudgetManager, token_estimator, tool_trace_blocks
from app.agent.context.cache_policy import cache_policy
from app.agent.context.repair import repair_unresolved_tool_calls
from app.agent.context.summary import ConversationSummaryManager, turn_hash
from app.agent.context.validator import context_validator
from app.agent.context.models import CacheEpochMeta
from app.agent.context.status import build_agent_status, render_agent_status
from app.agent.context.models import (
    ContextDiagnostics,
    ContextInvariantError,
    ContextEnvelope,
    ContextRequest,
    ConversationSummary,
    ConversationTurn,
    CurrentUserTurn,
    PreparedContext,
    SessionSnapshot,
    ToolObservation,
)
from app.core.config import settings
from app.core.logging import logger
from app.schemas import Message

# token 估算统一由 budget.TokenEstimator 提供（单一实现，避免双 tokenizer）
_count_tokens_tiktoken = token_estimator.count_messages


def dump_messages(messages: list[Message]) -> list[dict]:
    """把消息列表转换为字典列表.

    Args:
        messages (list[Message]): 待转换的消息。

    Returns:
        list[dict]: 转换后的字典列表。
    """
    return [message.model_dump() for message in messages]


def extract_text_content(content: str | list) -> str:
    """从 LLM 的 content 中提取纯文本.

    兼容两种格式：简单字符串，以及 GPT-5 / Responses API 模型返回的
    结构化块列表：
        [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}]

    Args:
        content: LangChain BaseMessage 的原始 content。

    Returns:
        纯文本字符串（无可提取内容时返回空字符串）。
    """
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "reasoning":
                logger.debug(
                    "reasoning_block_received",
                    reasoning_id=block.get("id"),
                    has_summary=bool(block.get("summary")),
                )
    return "".join(parts)


def process_llm_response(response: BaseMessage) -> BaseMessage:
    """归一化 LLM 原始响应，让 ``response.content`` 始终是纯字符串，不受厂家内容格式影响.

    Args:
        response: LLM 的原始响应。

    Returns:
        同一个 BaseMessage 实例，``content`` 已设置为纯字符串。
    """
    if isinstance(response.content, list):
        response.content = extract_text_content(response.content)
        logger.debug(
            "processed_structured_content",
            content_block_count=len(response.content),
            extracted_length=len(response.content),
        )
    return response


def prepare_messages(messages: list[BaseMessage], system_prompt: str) -> list[BaseMessage]:
    """为 LLM 准备消息列表：系统提示词 + 预算内的最近历史.

    无论会话历史多长、尾巴里有多少工具消息，用户最新的一条提问
    都必须保留在上下文里——否则模型完全看不到问题，只会盲目循环
    调用工具（这是会话被工具循环"污染"后必然复现的故障）。

    Args:
        messages (list[BaseMessage]): 会话消息（不含系统提示词）。
        system_prompt (str): 系统提示词。

    Returns:
        list[BaseMessage]: 组装完成的消息列表。
    """
    messages, _ = repair_unresolved_tool_calls(messages)
    try:
        trimmed = _trim_messages(
            messages,
            strategy="last",
            token_counter=_count_tokens_tiktoken,
            max_tokens=settings.CONTEXT_TOKEN_BUDGET,
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
    except ValueError as e:
        # 处理无法识别的内容块（例如 GPT-5 的 reasoning 块）
        if "Unrecognized content block type" in str(e):
            logger.warning(
                "token_counting_failed_skipping_trim",
                error=str(e),
                message_count=len(messages),
            )
            # 跳过修剪，原样返回全部消息
            trimmed = messages
        else:
            raise

    # start_on="human" 的副作用：长工具调用链的尾巴里可能没有任何 human
    # 消息，修剪器会把窗口整段删空。此时回退为"从最后一条 human 开始"，
    # 再在预算内保留尽量新的消息，保证用户的问题永远可见。
    if not trimmed or trimmed[0].type != "human":
        last_human = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1)
        trimmed = _fit_budget(messages[last_human:]) if last_human >= 0 else []

    return [SystemMessage(content=system_prompt), *trimmed]


def _fit_budget(messages: list[BaseMessage]) -> list[BaseMessage]:
    """在 token 预算内保留尽量新的消息，但首条（最后的提问）永远保留.

    Args:
        messages: 以最后的 human 提问开头的消息切片。

    Returns:
        list[BaseMessage]: 保持时间顺序、总量不超过预算的消息。
    """
    if not messages:
        return []
    kept = [messages[0]]
    total = _count_tokens_tiktoken(kept)
    kept_blocks: list[list[BaseMessage]] = []
    for block in reversed(tool_trace_blocks(messages[1:])):
        cost = _count_tokens_tiktoken(block)
        if total + cost > settings.CONTEXT_TOKEN_BUDGET:
            break
        kept_blocks.append(block)
        total += cost
    return [kept[0], *(message for block in reversed(kept_blocks) for message in block)]


class ContextManager:
    """结构化上下文管理器：去重 → 预算 → 组装 → 度量 → 校验.

    编排职责（任务书 §4/§25）：业务字段的裁剪属于 tools 层；
    LangGraph 消息协议（AI ToolCall → ToolMessage）保持原样不重写。
    """

    def __init__(self) -> None:
        """初始化预算管理器与校验器."""
        self.budget = ContextBudgetManager(
            token_estimator,
            max_single_tool_message_tokens=settings.TOOL_MESSAGE_HARD_LIMIT_TOKENS,
        )
        self.validator = context_validator
        # Phase 2：会话摘要（按 thread 键控，进程内存储）与 Cache Epoch 生命周期
        self.summary_manager = ConversationSummaryManager()
        # 分段摘要：每段覆盖一批旧 Turn，生成后冻结不重写（避免迭代漂移）
        self._summaries: dict[str, list[ConversationSummary]] = {}
        self._epochs: dict[str, CacheEpochMeta] = {}
        # 摘要状态落在 session.context_state（见 state_store）；这是"已恢复"标记
        self._state_loaded: set[str] = set()
        self._locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
        self._generations: dict[str, int] = {}

    async def prepare(
        self, messages: list, *, system_message: str, request: ContextRequest, **kwargs: Any
    ) -> PreparedContext:
        """同一进程按会话串行准备；跨进程写入由数据库 CAS 保护."""
        thread_key = request.conversation_id or ""
        lock = self._locks.setdefault(thread_key, Lock())
        async with lock:
            return await self._prepare(messages, system_message=system_message, request=request, **kwargs)

    async def _prepare(
        self,
        messages: list,
        *,
        system_message: str,
        request: ContextRequest,
        business_context: dict | None = None,
        session_snapshot: SessionSnapshot | None = None,
        runtime_tail: str | None = None,
        system_prompt_version: str | None = None,
        tools_version: str | None = None,
        tool_schemas: list | None = None,
    ) -> PreparedContext:
        """把会话消息组装成可安全发给 LLM 的上下文.

        Raises:
            ContextInvariantError: CURRENT_USER_TURN_MISSING /
                CONTEXT_BUDGET_EXCEEDED / ONLY_SYSTEM_MESSAGE 等不变量被破坏。
        """
        # 中断遗留的悬空 ToolCall 先补齐配对，否则校验器会永久拒绝该会话
        messages, repaired = repair_unresolved_tool_calls(messages)
        thread_key = request.conversation_id or ""
        if repaired:
            logger.warning(
                "context_dangling_tool_calls_repaired",
                repaired_count=repaired,
                thread=thread_key,
            )
        current_turn = self._find_current_user_turn(messages)
        all_turns = self._group_messages_into_turns(messages)
        # 进程重启后从 session.context_state 恢复摘要段与水位线（无状态则视为空）；
        # 摘要功能关闭时完全不加载——开关语义是"功能不可见"
        generation = self._generations.get(thread_key, 0)
        revision = 0
        state_available = True
        if settings.CONVERSATION_SUMMARY_ENABLED:
            try:
                revision = await self._ensure_state_loaded(thread_key)
            except ContextInvariantError:
                raise
            except Exception:
                logger.exception("context_state_load_failed", thread=thread_key)
                state_available = False
        segments = (
            self._summaries.get(thread_key, []) if settings.CONVERSATION_SUMMARY_ENABLED and state_available else []
        )
        # 即使 checkpoint 被替换或截短，也不能把新原文套上旧的整数水位线。
        if segments:
            expected = [source for segment in segments for source in segment.source_turn_hashes]
            actual = [turn_hash(turn) for turn in all_turns[: len(expected)]]
            if actual != expected or len(expected) >= len(all_turns):
                logger.warning("context_summary_source_changed", thread=thread_key)
                segments = []

        # ---- 水位线（Phase 2）：已压缩进摘要段的 Turn 数量 ----
        # checkpoint 只追加（Turn 位置稳定），整数水位线长期有效；
        # 最后一个 Turn 永远视为当前轮，不参与水位线。
        covered = segments[-1].source_end if segments else 0
        # [ :covered] 已由摘要代表；[covered:] 为未压缩区（本轮窗口来源）
        uncompacted_turns = all_turns[covered:]

        current_group = uncompacted_turns[-1]
        current_messages = [current_group.user_message, *current_group.following_messages]
        previous_turns = list(uncompacted_turns[:-1])

        # ---- AgentStatus（确定性，Phase 2 Step 1）----
        agent_status = None
        if settings.AGENT_STATUS_ENABLED:
            agent_status = build_agent_status(
                run_id=request.run_id,
                current_turn=current_turn,
                current_turn_messages=current_messages,
            )

        # ---- Batch Compaction（Phase 2；仅已完成旧 Turn；失败不删任何内容）----
        compaction_failed = False
        rollover_count = 0
        compaction_result = None
        epoch = self._epochs.get(
            thread_key,
            CacheEpochMeta(epoch_id=f"{thread_key or 'thread'}:e1", sequence=1),
        )
        # 触发与最终预算使用同一套消息计数，包含摘要标题、动态尾部及工具 schema。
        probe = ContextEnvelope(
            current_turn=current_turn,
            current_turn_messages=current_messages,
            recent_turns=previous_turns,
            conversation_summary=segments,
            agent_status=agent_status,
        )
        schema_tokens = token_estimator.count_tool_schemas(tool_schemas)
        estimated_total = (
            token_estimator.count_messages(self._assemble_messages(system_message, probe, runtime_tail))
            + schema_tokens
        )
        output_limit = max(64, min(2048, request.max_context_tokens // 8))
        input_limit = max(1, request.max_context_tokens - output_limit)

        def ensure_candidate_fits(candidate: list[ConversationSummary]) -> None:
            """拒绝无法容纳当前轮的摘要状态，避免落盘后让会话永久超预算."""
            fixed = ContextEnvelope(
                current_turn=current_turn, conversation_summary=candidate, agent_status=agent_status
            )
            fixed_cost = (
                token_estimator.count_messages(self._assemble_messages(system_message, fixed, runtime_tail))
                + schema_tokens
            )
            trace = ContextEnvelope(current_turn=current_turn, current_turn_messages=current_messages)
            try:
                self.budget.fit(trace, request.max_context_tokens, fixed_cost)
            except ContextInvariantError as exc:
                raise ValueError("summary candidate leaves insufficient room for the current turn") from exc

        if (
            settings.BATCH_COMPACTION_ENABLED
            and settings.CONVERSATION_SUMMARY_ENABLED
            and state_available
            and len(previous_turns) >= max(3, settings.CONTEXT_COMPACTION_MIN_TURNS)
            and cache_policy.should_compact(estimated_total, request.max_context_tokens)
        ):
            try:
                compaction_result = await self.summary_manager.compact(
                    turns=previous_turns[:-2],
                    source_start=covered,
                    version=max((segment.version for segment in segments), default=0) + 1,
                    input_token_limit=input_limit,
                    output_token_limit=output_limit,
                )
                candidate = [*segments, compaction_result.summary]
                ensure_candidate_fits(candidate)
                candidate_epoch = CacheEpochMeta(
                    epoch_id=f"{thread_key}:e{epoch.sequence + 1}",
                    sequence=epoch.sequence + 1,
                    summary_version=compaction_result.summary.version,
                    created_at=compaction_result.summary.updated_at,
                )
                revision = await self._persist_state(thread_key, candidate, candidate_epoch, revision, generation)
                segments = candidate
                epoch = candidate_epoch
                previous_turns = previous_turns[compaction_result.compacted_turn_count :]
                rollover_count += 1
            except ContextInvariantError:
                raise
            except Exception:
                compaction_result = None
                compaction_failed = True
                logger.exception("context_compaction_failed", thread=thread_key)

        # 只合并最旧的配置比例；失败时原段保持不变，不推进 Epoch。
        if settings.CONVERSATION_SUMMARY_ENABLED and state_available and len(segments) >= 2:
            region_tokens = token_estimator.count_messages(
                self._assemble_messages("", ContextEnvelope(current_turn=current_turn, conversation_summary=segments))
            )
            if (
                cache_policy.usage_ratio(region_tokens, request.max_context_tokens) > settings.SUMMARY_REGION_MAX_RATIO
                or len(segments) > settings.SUMMARY_SEGMENT_MERGE_COUNT
            ):
                try:
                    candidate, merged_pairs = await self._merge_oldest_pairwise(segments, input_limit, output_limit)
                    ensure_candidate_fits(candidate)
                    candidate_epoch = CacheEpochMeta(
                        epoch_id=f"{thread_key}:e{epoch.sequence + 1}",
                        sequence=epoch.sequence + 1,
                        summary_version=max(segment.version for segment in candidate),
                    )
                    revision = await self._persist_state(thread_key, candidate, candidate_epoch, revision, generation)
                    segments, epoch = candidate, candidate_epoch
                    rollover_count += 1
                    logger.info("summary_segments_merged", merged_pairs=merged_pairs, segment_count=len(segments))
                except ContextInvariantError:
                    raise
                except Exception:
                    compaction_failed = True
                    logger.exception("context_summary_merge_failed", thread=thread_key)

        envelope = ContextEnvelope(
            current_turn=current_turn,
            current_turn_messages=current_messages,
            recent_turns=previous_turns,
            conversation_summary=segments,
            agent_status=agent_status,
            business_context=business_context,
        )

        fixed_envelope = ContextEnvelope(
            current_turn=current_turn,
            conversation_summary=segments,
            agent_status=agent_status,
        )
        system_cost = (
            token_estimator.count_messages(self._assemble_messages(system_message, fixed_envelope, runtime_tail))
            + schema_tokens
        )
        envelope, dedup_removed, compacted, dropped = self.budget.fit(
            envelope,
            request.max_context_tokens,
            system_cost,
        )
        envelope.tool_observations = self._build_tool_observations(envelope.current_turn_messages)

        prepared_messages = self._assemble_messages(system_message, envelope, runtime_tail)

        # ---- 机制性兜底：按真实计数逐出最老的未压缩 Turn ----
        # Turn 的 estimated_tokens 与整表计数的启发式存在少量误差
        # （每条 +4 开销的口径差），累计后会让选择"乐观"几十 token，
        # 导致最终总量小幅超预算。这里用真实计数逐出，保证精确合规。
        evicted = 0
        while (
            envelope.recent_turns
            and token_estimator.count_messages(prepared_messages) + schema_tokens > request.max_context_tokens
        ):
            envelope.recent_turns.pop(0)
            evicted += 1
            prepared_messages = self._assemble_messages(system_message, envelope, runtime_tail)
        dropped += evicted

        summary_segments = envelope.conversation_summary
        latest_summary = max(summary_segments, key=lambda segment: segment.version) if summary_segments else None
        agent_status_tokens = (
            token_estimator.count_text(render_agent_status(envelope.agent_status)) if envelope.agent_status else None
        )
        diagnostics = self._measure(
            prepared_messages,
            envelope,
            request.max_context_tokens,
            system_message=system_message,
            session_snapshot=session_snapshot,
            system_prompt_version=system_prompt_version,
            tools_version=tools_version,
            tool_schemas=tool_schemas,
            dedup_removed=dedup_removed,
            tool_observations_compacted=compacted,
            dropped_turn_count=dropped,
            summary_version=latest_summary.version if latest_summary else None,
            summary_tokens=(
                sum(token_estimator.count_text(segment.content) for segment in summary_segments)
                if summary_segments
                else None
            ),
            compacted_turn_count=compaction_result.compacted_turn_count if compaction_result else 0,
            compaction_failed=compaction_failed,
            cache_epoch_sequence=epoch.sequence,
            epoch_rollover_count=rollover_count,
            agent_status_tokens=agent_status_tokens,
        )
        self.validator.validate(prepared_messages, envelope, diagnostics)
        if settings.CONVERSATION_SUMMARY_ENABLED and state_available and thread_key:
            latest_state = await state_store.load_context_state(thread_key)
            if (
                not latest_state.exists
                or latest_state.revision != revision
                or self._generations.get(thread_key, 0) != generation
            ):
                raise ContextInvariantError("CONTEXT_STATE_CHANGED", "会话在准备期间已变化，请重试")

        logger.info(
            "context_prepared",
            total_tokens=diagnostics.total_tokens,
            message_count=diagnostics.message_count,
            current_user_present=diagnostics.current_user_present,
            recent_turn_count=diagnostics.recent_turn_count,
            tool_observation_count=diagnostics.tool_observation_count,
            duplicate_tool_observations_removed=diagnostics.duplicate_tool_observations_removed,
            tool_observations_compacted=diagnostics.tool_observations_compacted,
            dropped_turn_count=diagnostics.dropped_turn_count,
            usage_ratio=diagnostics.context_usage_ratio,
            should_compact=diagnostics.should_compact,
            cache_epoch_id=diagnostics.cache_epoch_id,
            global_prefix_hash=diagnostics.global_prefix_hash,
            summary_version=diagnostics.summary_version,
            summary_tokens=diagnostics.summary_tokens,
            compacted_turn_count=diagnostics.compacted_turn_count,
            compaction_failed=diagnostics.compaction_failed,
            cache_epoch_sequence=diagnostics.cache_epoch_sequence,
            epoch_rollover_count=diagnostics.epoch_rollover_count,
            agent_status_tokens=diagnostics.agent_status_tokens,
        )
        return PreparedContext(messages=prepared_messages, envelope=envelope, diagnostics=diagnostics)

    async def _ensure_state_loaded(self, thread_key: str) -> int:
        """每次读取数据库修订号，清空或其他 worker 的更新立即使本地缓存失效."""
        if not thread_key:
            return 0
        state = await state_store.load_context_state(thread_key)
        if not state.exists:
            raise ContextInvariantError("CONTEXT_STATE_CHANGED", "会话已删除，请重新打开会话")
        self._summaries.pop(thread_key, None)
        self._epochs.pop(thread_key, None)
        if state.segments:
            self._summaries[thread_key] = state.segments
        if state.segments or state.epoch_sequence > 1:
            self._epochs[thread_key] = CacheEpochMeta(
                epoch_id=f"{thread_key}:e{state.epoch_sequence}",
                sequence=state.epoch_sequence,
            )
        self._state_loaded.add(thread_key)
        return state.revision

    async def _persist_state(
        self,
        thread_key: str,
        segments: list[ConversationSummary],
        epoch: CacheEpochMeta,
        revision: int,
        generation: int,
    ) -> int:
        """先提交数据库，再发布到内存；CAS 失败说明会话在压缩期间已变化."""
        state_store.validate_segments(segments)
        if thread_key:
            saved = await state_store.save_context_state(
                thread_key,
                segments,
                epoch.sequence,
                expected_revision=revision,
            )
            if not saved:
                self.forget_thread(thread_key)
                raise ContextInvariantError("CONTEXT_STATE_CHANGED", "会话在压缩期间已变化，请重试")
            revision += 1
        if self._generations.get(thread_key, 0) != generation:
            raise ContextInvariantError("CONTEXT_STATE_CHANGED", "会话已清空，请重试")
        self._summaries[thread_key] = segments
        self._epochs[thread_key] = epoch
        return revision

    def forget_thread(self, thread_key: str) -> None:
        """清空/删除后立即失效本地状态；使正在执行的旧摘要无法发布."""
        self._summaries.pop(thread_key, None)
        self._epochs.pop(thread_key, None)
        self._state_loaded.discard(thread_key)
        self._generations[thread_key] = self._generations.get(thread_key, 0) + 1

    async def _merge_oldest_pairwise(
        self,
        segments: list[ConversationSummary],
        input_limit: int,
        output_limit: int,
    ) -> tuple[list[ConversationSummary], int]:
        """按配置比例选最旧的偶数段，逐对合并，所有调用成功后一次发布."""
        fraction = min(1.0, max(0.0, settings.SUMMARY_MERGE_FRACTION))
        to_merge_count = min(len(segments) // 2 * 2, max(2, ceil(len(segments) * fraction) // 2 * 2))
        merged: list[ConversationSummary] = []
        version = max(segment.version for segment in segments)
        for index in range(0, to_merge_count, 2):
            version += 1
            result = await self.summary_manager.merge_segments(
                segments[index : index + 2],
                version=version,
                input_token_limit=input_limit,
                output_token_limit=output_limit,
            )
            merged.append(result.summary)
        return [*merged, *segments[to_merge_count:]], len(merged)

    @staticmethod
    def _find_current_user_turn(messages: list) -> CurrentUserTurn:
        """取最后一条真实 human 消息作为当前用户轮（P0，永不参与裁剪）."""
        for message in reversed(messages):
            if getattr(message, "type", None) == "human":
                return CurrentUserTurn(
                    content=str(message.content),
                    message_id=getattr(message, "id", None),
                )
        raise ContextInvariantError("CURRENT_USER_TURN_MISSING", "会话中找不到用户消息")

    @staticmethod
    def _group_messages_into_turns(messages: list) -> list[ConversationTurn]:
        """按 human 提问切分完整轮次：一条 human + 其后所有 AI/Tool 消息."""
        turns: list[ConversationTurn] = []
        for message in messages:
            if getattr(message, "type", None) == "human":
                turns.append(ConversationTurn(user_message=message, turn_id=getattr(message, "id", None)))
            elif turns:
                turns[-1].following_messages.append(message)
            else:
                # 首条 human 之前不允许出现 AI/Tool 消息；出现了就丢弃并记录
                logger.debug("context_leading_orphan_message_dropped", message_type=getattr(message, "type", None))
        for turn in turns:
            turn.estimated_tokens = token_estimator.count_messages([turn.user_message, *turn.following_messages])
        return turns

    @staticmethod
    def _build_tool_observations(current_messages: list) -> list[ToolObservation]:
        """从当前轮消息中提取工具观测记录（已经过 Tool 层裁剪）."""
        observations = []
        for message in current_messages:
            if getattr(message, "type", None) != "tool":
                continue
            content = str(message.content)
            observations.append(
                ToolObservation(
                    tool_name=message.name or "unknown",
                    content=content,
                    estimated_tokens=token_estimator.count_text(content),
                )
            )
        return observations

    @staticmethod
    def _assemble_messages(system_message: str, envelope, runtime_tail: str | None = None) -> list:
        """按顺序组装：系统提示词(L0) + 摘要段(L2) + 最近轮次(L3) + 当前轮(L3) + 动态尾部(L4).

        摘要段逐段追加（每段冻结）；Dynamic Tail 追加在最末尾——
        每轮变化的内容放尾部，不影响前面稳定内容的 KV Cache 前缀命中。
        """
        messages: list = [SystemMessage(content=system_message)]
        for segment in envelope.conversation_summary:
            # Conversation Summary（L2）：紧跟系统提示词，属于较稳定的前缀段
            messages.append(
                SystemMessage(
                    content=f"# 此前对话摘要（v{segment.version}，仅供你参考的背景信息，"
                    f"不要在回答中原样复述这段内容）" + chr(10) + segment.content
                )
            )
        for turn in envelope.recent_turns:
            messages.append(turn.user_message)
            messages.extend(turn.following_messages)
        messages.extend(envelope.current_turn_messages)
        if runtime_tail:
            messages.append(SystemMessage(content=runtime_tail))
        if envelope.agent_status:
            # AgentStatus（L4 Dynamic Tail）：放最末尾，每轮变化不影响前缀
            messages.append(SystemMessage(content=render_agent_status(envelope.agent_status)))
        return messages

    @staticmethod
    def _measure(
        prepared_messages,
        envelope,
        max_tokens,
        *,
        system_message,
        session_snapshot,
        system_prompt_version,
        tools_version,
        tool_schemas,
        dedup_removed,
        tool_observations_compacted,
        dropped_turn_count,
        summary_version=None,
        summary_tokens=None,
        compacted_turn_count=0,
        compaction_failed=False,
        cache_epoch_sequence=None,
        epoch_rollover_count=0,
        agent_status_tokens=None,
    ) -> ContextDiagnostics:
        """统计最终上下文的量化指标与 KV Cache 指纹（不含用户内容本身）."""
        total_tokens = token_estimator.count_messages(prepared_messages) + token_estimator.count_tool_schemas(
            tool_schemas
        )
        usage_ratio = cache_policy.usage_ratio(total_tokens, max_tokens)

        # 三层前缀指纹：L0 全局（系统提示词+工具 Schema）/ L1 会话（+快照）/ L2 Epoch
        global_prefix_hash = cache_policy.fingerprint({"system": system_message, "tools": tool_schemas or []})
        session_prefix_hash = cache_policy.fingerprint(
            {"global": global_prefix_hash, "snapshot": session_snapshot.model_dump() if session_snapshot else None}
        )
        cache_epoch_id = f"{system_prompt_version or 'v0'}:{tools_version or 'v0'}:{session_prefix_hash[:8]}"
        epoch_prefix_hash = cache_policy.fingerprint(
            {
                "session": session_prefix_hash,
                "sequence": cache_epoch_sequence,
                "segments": [segment.model_dump(mode="json") for segment in envelope.conversation_summary],
            }
        )
        cache_epoch_id = f"{cache_epoch_id}:e{cache_epoch_sequence or 1}:{epoch_prefix_hash[:8]}"

        return ContextDiagnostics(
            total_tokens=total_tokens,
            message_count=len(prepared_messages),
            max_context_tokens=max_tokens,
            current_user_present=any(
                getattr(m, "type", None) == "human" and getattr(m, "content", None) == envelope.current_turn.content
                for m in prepared_messages
            ),
            recent_turn_count=len(envelope.recent_turns),
            tool_observation_count=len(envelope.tool_observations),
            duplicate_tool_observations_removed=dedup_removed,
            tool_observations_compacted=tool_observations_compacted,
            dropped_turn_count=dropped_turn_count,
            system_prompt_version=system_prompt_version,
            tools_version=tools_version,
            cache_epoch_id=cache_epoch_id,
            global_prefix_hash=global_prefix_hash,
            session_prefix_hash=session_prefix_hash,
            epoch_prefix_hash=epoch_prefix_hash,
            context_usage_ratio=round(usage_ratio, 4),
            should_compact=cache_policy.should_compact(total_tokens, max_tokens),
            summary_version=summary_version,
            summary_tokens=summary_tokens,
            compacted_turn_count=compacted_turn_count,
            compaction_failed=compaction_failed,
            cache_epoch_sequence=cache_epoch_sequence,
            epoch_rollover_count=epoch_rollover_count,
            agent_status_tokens=agent_status_tokens,
        )


context_manager = ContextManager()
