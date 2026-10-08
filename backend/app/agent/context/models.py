"""Context 数据模型与不变量异常.

这些模型是 ContextManager 内部的逻辑视图：LangGraph 的消息协议
（HumanMessage / AIMessage / ToolMessage）保持不变，Envelope 只负责
记账与裁剪决策。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ContextInvariantError(RuntimeError):
    """上下文不变量被破坏——必须中止本次调用，禁止继续请求 LLM."""

    def __init__(self, code: str, message: str = "") -> None:
        """携带机器可读错误码，便于上层（接口/前端）区分处理."""
        self.code = code
        message = message or code
        super().__init__(message)


class ContextRequest(BaseModel):
    """一次上下文组装的请求参数."""

    conversation_id: str | None = None
    run_id: str | None = None
    max_context_tokens: int = 16384


class CurrentUserTurn(BaseModel):
    """当前用户的提问——最高优先级上下文（P0，不可删除、不可压缩）."""

    content: str
    message_id: str | None = None
    turn_id: str | None = None
    created_at: datetime | None = None


class ConversationTurn(BaseModel):
    """一个完整对话轮次：一条 human 提问 + 其后所有 AI/工具消息."""

    user_message: Any
    following_messages: list[Any] = Field(default_factory=list)
    turn_id: str | None = None
    estimated_tokens: int = 0


class ToolObservation(BaseModel):
    """当前轮次里一次工具结果的可观测记录（已经过 Tool 层裁剪）."""

    tool_name: str
    content: str
    arguments_hash: str | None = None
    success: bool = True
    estimated_tokens: int = 0


class SessionSnapshot(BaseModel):
    """会话级快照（L1）：会话开始时冻结，当前 Conversation 内不再刷新.

    Memory Write 可以实时（mem0 后台写），但 Memory Injection 用这里的
    快照——保证会话内系统提示词前缀逐字节稳定（KV Cache 友好）。
    """

    memory_snapshot: str = ""
    user_profile: dict | None = None
    business_defaults: dict | None = None
    version: str | None = None


class ContextEnvelope(BaseModel):
    """裁剪前的逻辑上下文包裹.

    current_turn_messages 保存当前轮的原始协议消息（保持 LangGraph 的
    AI ToolCall → ToolMessage 配对关系不被重排）。
    """

    current_turn: CurrentUserTurn
    current_turn_messages: list[Any] = Field(default_factory=list)
    recent_turns: list[ConversationTurn] = Field(default_factory=list)
    conversation_summary: list["ConversationSummary"] = Field(default_factory=list)
    agent_status: "AgentStatus | None" = None
    tool_observations: list[ToolObservation] = Field(default_factory=list)
    business_context: dict | None = None


class ContextDiagnostics(BaseModel):
    """每次上下文构建的量化观测（不含用户内容本身）."""

    total_tokens: int = 0
    message_count: int = 0
    max_context_tokens: int = 0
    current_user_present: bool = False

    recent_turn_count: int = 0
    tool_observation_count: int = 0

    duplicate_tool_observations_removed: int = 0
    tool_observations_compacted: int = 0
    dropped_turn_count: int = 0

    # KV Cache 可观测字段
    system_prompt_version: str | None = None
    tools_version: str | None = None
    cache_epoch_id: str | None = None
    global_prefix_hash: str | None = None
    session_prefix_hash: str | None = None
    epoch_prefix_hash: str | None = None
    context_usage_ratio: float | None = None
    should_compact: bool = False

    # Phase 2
    summary_version: int | None = None
    summary_tokens: int | None = None
    compacted_turn_count: int = 0
    compaction_failed: bool = False
    cache_epoch_sequence: int | None = None
    epoch_rollover_count: int = 0
    agent_status_tokens: int | None = None


class PreparedContext(BaseModel):
    """ContextManager 的对外产物：最终消息 + 逻辑信封 + 诊断."""

    messages: list[Any]
    envelope: ContextEnvelope
    diagnostics: ContextDiagnostics


class AgentStatus(BaseModel):
    """当前 Run 的确定性状态（程序生成，非 LLM 推断），放 Dynamic Tail."""

    run_id: str | None = None
    goal: str | None = None
    current_entity: dict | None = None

    tool_call_count: int = 0
    tool_calls_by_name: dict[str, int] = Field(default_factory=dict)
    duplicate_tool_calls: list[str] = Field(default_factory=list)

    completed_steps: list[str] = Field(default_factory=list)
    pending_steps: list[str] = Field(default_factory=list)

    last_tool_name: str | None = None
    last_error: str | None = None

    warnings: list[str] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    """已完成旧 Turn 的批量压缩摘要（只保留未来回答仍需要的信息）."""

    content: str
    version: int = 1
    covered_turn_count: int = 0
    covered_until_turn_id: str | None = None
    covered_from_turn_id: str | None = None
    source_start: int = 0
    source_end: int = 0
    source_turn_hashes: list[str] = Field(default_factory=list)
    source_hash: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CompactionResult(BaseModel):
    """一次 Batch Compaction 的结果."""

    summary: ConversationSummary
    compacted_turn_count: int
    remaining_turn_count: int


class CacheEpochMeta(BaseModel):
    """一段 Context Prefix 尽量保持稳定的生命周期."""

    epoch_id: str
    sequence: int = 1
    summary_version: int | None = None
    created_at: datetime | None = None


# 前向引用在文件后部定义，这里统一重建 Schema
ContextEnvelope.model_rebuild()
