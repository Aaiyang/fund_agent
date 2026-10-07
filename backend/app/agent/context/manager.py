"""Agent 上下文组装工具：历史修剪、消息转换与 token 估算."""

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
)
from langchain_core.messages import trim_messages as _trim_messages

from app.agent.context import state_store
from app.agent.context.budget import ContextBudgetManager, token_estimator
from app.agent.context.cache_policy import cache_policy
from app.agent.context.models import CacheEpochMeta
from app.agent.context.status import build_agent_status, render_agent_status
from app.agent.context.models import (
    ContextDiagnostics,
    ContextInvariantError,
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
    for msg in reversed(messages[1:]):
        cost = _count_tokens_tiktoken([msg])
        if total + cost > settings.CONTEXT_TOKEN_BUDGET:
            break
        kept.append(msg)
        total += cost
    # kept 目前是 [提问, 最新, 次新...]，恢复成时间顺序
    return [kept[0], *reversed(kept[1:])]


class ContextManager:
    """结构化上下文管理器：去重 → 预算 → 组装 → 度量 → 校验.

    编排职责（任务书 §4/§25）：业务字段的裁剪属于 tools 层；
    LangGraph 消息协议（AI ToolCall → ToolMessage）保持原样不重写。
    """

    def __init__(self) -> None:
        """初始化预算管理器与校验器."""
        from app.agent.context.validator import context_validator

        self.budget = ContextBudgetManager(
            token_estimator,
            max_single_tool_message_tokens=settings.TOOL_MESSAGE_HARD_LIMIT_TOKENS,
        )
        self.validator = context_validator
        # Phase 2：会话摘要（按 thread 键控，进程内存储）与 Cache Epoch 生命周期
        from app.agent.context.summary import ConversationSummaryManager

        self.summary_manager = ConversationSummaryManager()
        # 分段摘要：每段覆盖一批旧 Turn，生成后冻结不重写（避免迭代漂移）
        self._summaries: dict[str, list[ConversationSummary]] = {}
        self._epochs: dict[str, CacheEpochMeta] = {}
        # 摘要状态落在 session.context_state（见 state_store）；这是"已恢复"标记
        self._state_loaded: set[str] = set()

    async def prepare(
        self,
        messages: list,
        *,
        system_message: str,
        request,
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
        from app.agent.context.models import (
            ContextEnvelope,
            PreparedContext,
        )

        current_turn = self._find_current_user_turn(messages)
        all_turns = self._group_messages_into_turns(messages)

        thread_key = request.conversation_id or ""
        # 进程重启后从 session.context_state 恢复摘要段与水位线（无状态则视为空）；
        # 摘要功能关闭时完全不加载——开关语义是"功能不可见"
        if settings.CONVERSATION_SUMMARY_ENABLED:
            await self._ensure_state_loaded(thread_key)
        segments = self._summaries.get(thread_key, [])

        # ---- 水位线（Phase 2）：已压缩进摘要段的 Turn 数量 ----
        # checkpoint 只追加（Turn 位置稳定），整数水位线长期有效；
        # 最后一个 Turn 永远视为当前轮，不参与水位线。
        covered = min(
            sum(segment.covered_turn_count for segment in segments),
            max(len(all_turns) - 1, 0),
        )
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
        if settings.BATCH_COMPACTION_ENABLED and settings.CONVERSATION_SUMMARY_ENABLED and previous_turns:
            estimated_total = (
                token_estimator.count_text(system_message)
                + token_estimator.count_messages(current_messages)
                + sum(turn.estimated_tokens for turn in previous_turns)
            )
            min_turns = settings.CONTEXT_COMPACTION_MIN_TURNS
            if (
                cache_policy.should_compact(estimated_total, request.max_context_tokens)
                and len(previous_turns) >= min_turns
            ):
                keep_recent = 2
                # 压缩范围 = 全部"未压缩"的 previous Turn，除最近 2 个外全部进摘要；
                # 成功后水位线随 summary.covered_turn_count 前移。
                old_batch = previous_turns[: len(previous_turns) - keep_recent]
                try:
                    compaction_result = await self.summary_manager.compact(
                        previous_summary=segments[-1] if segments else None,
                        turns=old_batch,
                    )
                    # 分段：新段追加（旧段冻结不重写，避免迭代漂移）
                    segments = [*segments, compaction_result.summary]
                    self._summaries[thread_key] = segments
                    previous_turns = previous_turns[-keep_recent:]
                    rollover_count = 1
                    old_sequence = epoch.sequence
                    epoch = CacheEpochMeta(
                        epoch_id=f"{epoch.epoch_id.split('#')[0]}#e{epoch.sequence + 1}",
                        sequence=epoch.sequence + 1,
                        summary_version=compaction_result.summary.version,
                        created_at=compaction_result.summary.updated_at,
                    )
                    self._epochs[thread_key] = epoch
                    logger.info(
                        "cache_epoch_rollover",
                        old_epoch=old_sequence,
                        new_epoch=epoch.sequence,
                        summary_version=compaction_result.summary.version,
                        compacted_turn_count=compaction_result.compacted_turn_count,
                    )
                    await self._persist_state(thread_key)
                except Exception:
                    # 压缩失败：不删除旧 Turn、不 rollover，继续用现有上下文
                    compaction_failed = True
                    logger.exception("context_compaction_failed")

        # 摘要区占比超上限（或段数超硬上限）：对最旧的一半段做两两合并
        # （size-tiered 模式：段覆盖的 Turn 数逐级翻倍，段数对数增长；
        #   每对一次 LLM 调用，输入仅两段，摘要质量高、漂移单次可控）
        if settings.CONVERSATION_SUMMARY_ENABLED and len(segments) >= 2:
            region_tokens = sum(token_estimator.count_text(segment.content) for segment in segments)
            region_ratio = cache_policy.usage_ratio(region_tokens, request.max_context_tokens)
            if (
                region_ratio > settings.SUMMARY_REGION_MAX_RATIO
                or len(segments) > settings.SUMMARY_SEGMENT_MERGE_COUNT
            ):
                segments, merged_pairs = await self._merge_oldest_pairwise(segments)
                self._summaries[thread_key] = segments
                rollover_count += 1
                latest_version = max(segment.version for segment in segments)
                epoch = CacheEpochMeta(
                    epoch_id=f"{epoch.epoch_id.split('#')[0]}#e{epoch.sequence + 1}",
                    sequence=epoch.sequence + 1,
                    summary_version=latest_version,
                    created_at=None,
                )
                self._epochs[thread_key] = epoch
                logger.info(
                    "summary_segments_merged",
                    merged_pairs=merged_pairs,
                    segment_count=len(segments),
                    region_ratio=round(region_ratio, 4),
                )
                await self._persist_state(thread_key)

        envelope = ContextEnvelope(
            current_turn=current_turn,
            current_turn_messages=current_messages,
            recent_turns=previous_turns,
            conversation_summary=segments,
            agent_status=agent_status,
            business_context=business_context,
        )

        system_cost = token_estimator.count_text(system_message)
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
        while envelope.recent_turns and token_estimator.count_messages(prepared_messages) > request.max_context_tokens:
            envelope.recent_turns.pop(0)
            evicted += 1
            prepared_messages = self._assemble_messages(system_message, envelope, runtime_tail)
        dropped += evicted

        summary_segments = envelope.conversation_summary
        latest_summary = summary_segments[-1] if summary_segments else None
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

    async def _ensure_state_loaded(self, thread_key: str) -> None:
        """进程重启后从 session.context_state 恢复摘要段与 Epoch（每线程至多读一次）.

        已在内存里的线程跳过（含测试直接注入的场景）；行不存在或载荷
        损坏视为无状态——下次达到阈值时重新压缩，只是多一次 LLM 调用。
        """
        if not thread_key or thread_key in self._state_loaded or thread_key in self._summaries:
            return
        self._state_loaded.add(thread_key)
        try:
            state = await state_store.load_context_state(thread_key)
        except Exception:
            logger.exception("context_state_load_failed", thread=thread_key)
            return
        if not state:
            return
        segments, epoch_sequence = state
        if segments:
            self._summaries[thread_key] = segments
            self._epochs[thread_key] = CacheEpochMeta(
                epoch_id=f"{thread_key or 'thread'}:e{epoch_sequence}",
                sequence=epoch_sequence,
            )
            logger.info(
                "context_state_restored",
                thread=thread_key,
                segment_count=len(segments),
                epoch_sequence=epoch_sequence,
            )

    async def _persist_state(self, thread_key: str) -> None:
        """压缩/合并后把摘要段与 Epoch 写回会话行；失败只记日志，不阻塞请求."""
        if not thread_key:
            return
        segments = self._summaries.get(thread_key, [])
        epoch = self._epochs.get(thread_key)
        try:
            await state_store.save_context_state(thread_key, segments, epoch.sequence if epoch else 1)
        except Exception:
            logger.exception("context_state_persist_failed", thread=thread_key)

    def forget_thread(self, thread_key: str) -> None:
        """会话删除后丢弃进程内的摘要状态（防止残留与误恢复）."""
        self._summaries.pop(thread_key, None)
        self._epochs.pop(thread_key, None)
        self._state_loaded.discard(thread_key)

    async def _merge_oldest_pairwise(self, segments: list) -> tuple[list, int]:
        """把最旧的偶数个段两两合并，段数约减半（size-tiered 模式）.

        每对一次 LLM 调用，输入只有两段全文——摘要质量高、漂移单次可控；
        落单段原样保留。返回（新段列表, 合并对数）。
        """
        to_merge_count = max(2, (len(segments) // 2) * 2)
        to_merge = segments[:to_merge_count]
        remainder = segments[to_merge_count:]

        merged: list = []
        llm_calls = 0
        for i in range(0, len(to_merge), 2):
            pair = to_merge[i : i + 2]
            result = await self.summary_manager.merge_segments(pair)
            merged.append(result.summary)
            llm_calls += 1
        return [*merged, *remainder], llm_calls

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
                turns.append(ConversationTurn(user_message=message))
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
        total_tokens = token_estimator.count_messages(prepared_messages)
        usage_ratio = cache_policy.usage_ratio(total_tokens, max_tokens)

        # 三层前缀指纹：L0 全局（系统提示词+工具 Schema）/ L1 会话（+快照）/ L2 Epoch
        global_prefix_hash = cache_policy.fingerprint({"system": system_message, "tools": tool_schemas or []})
        session_prefix_hash = cache_policy.fingerprint(
            {"global": global_prefix_hash, "snapshot": session_snapshot.model_dump() if session_snapshot else None}
        )
        cache_epoch_id = f"{system_prompt_version or 'v0'}:{tools_version or 'v0'}:{session_prefix_hash[:8]}"
        epoch_prefix_hash = cache_policy.fingerprint({"session": session_prefix_hash, "epoch": cache_epoch_id})

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
