"""会话线程状态的数据库持久化：摘要段 + LangGraph checkpoint 清理.

摘要段与 Cache Epoch 存在 ``session.context_state``（JSON 列）上——
随会话行存亡：删除会话即删除状态，天然按用户（session.user_id）隔离。
数据库是摘要状态的权威来源；每次准备上下文重新读取修订号。
压缩后的落盘使用 CAS，成功提交后才发布到进程内缓存。

同时提供 ``delete_thread_checkpoints``：删除会话时顺手清掉 LangGraph
checkpointer 在同一库里的三张表，避免对话内容成为孤儿。
"""

from sqlalchemy import text
from pydantic import BaseModel, Field
from sqlmodel import col, select, update

from app.agent.context.models import ConversationSummary
from app.agent.context.cache_policy import cache_policy
from app.core.database import get_async_session
from app.core.logging import logger
from app.models.session import Session as ChatSession

_STATE_VERSION = 2


class ContextStateRead(BaseModel):
    """数据库状态及其 CAS 修订号，空载荷也必须保留修订号."""

    segments: list[ConversationSummary] = Field(default_factory=list)
    epoch_sequence: int = 1
    revision: int = 0
    exists: bool = True


def validate_segments(segments: list[ConversationSummary]) -> None:
    """V2 摘要只能覆盖从零开始的连续、互不重叠轮次."""
    cursor = 0
    versions: set[int] = set()
    for segment in segments:
        if (
            not segment.content.strip()
            or segment.version < 1
            or segment.version in versions
            or segment.source_start != cursor
            or segment.source_end <= cursor
            or segment.covered_turn_count != segment.source_end - cursor
            or len(segment.source_turn_hashes) != segment.covered_turn_count
            or not all(segment.source_turn_hashes)
            or segment.source_hash != cache_policy.fingerprint(segment.source_turn_hashes)
        ):
            raise ValueError("invalid or overlapping summary sources")
        versions.add(segment.version)
        cursor = segment.source_end


_DELETE_CHECKPOINTS_SQL = text("DELETE FROM checkpoints WHERE thread_id = :thread_id")
_DELETE_BLOBS_SQL = text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id")
_DELETE_WRITES_SQL = text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id")


def serialize_state(segments: list[ConversationSummary], epoch_sequence: int) -> dict:
    """把摘要段与 Epoch 序号打包成可入库的 JSON 载荷（datetime 安全）."""
    validate_segments(segments)
    if epoch_sequence < 1:
        raise ValueError("invalid epoch sequence")
    return {
        "version": _STATE_VERSION,
        "segments": [segment.model_dump(mode="json") for segment in segments],
        "epoch_sequence": epoch_sequence,
    }


def parse_state(payload: dict | None) -> tuple[list[ConversationSummary], int] | None:
    """解析入库载荷；缺失、损坏或版本不识别一律视为无状态（None）."""
    if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
        return None
    segments_raw = payload.get("segments")
    sequence = payload.get("epoch_sequence")
    if not isinstance(segments_raw, list) or not isinstance(sequence, int) or sequence < 1:
        return None
    try:
        segments = [ConversationSummary.model_validate(segment) for segment in segments_raw]
        validate_segments(segments)
    except Exception:
        # 单段损坏视为整体不可信：进程内会重新压缩
        logger.warning("context_state_payload_invalid")
        return None
    return segments, sequence


async def load_context_state(thread_key: str) -> ContextStateRead:
    """读取摘要与修订号；V1/损坏载荷不恢复，缺失会话显式标记."""
    stmt = select(ChatSession.context_state, ChatSession.context_revision).where(col(ChatSession.id) == thread_key)
    async with get_async_session() as db:
        row = (await db.execute(stmt)).first()
    if row is None:
        return ContextStateRead(exists=False)
    parsed = parse_state(row[0])
    segments, sequence = parsed if parsed else ([], 1)
    return ContextStateRead(segments=segments, epoch_sequence=sequence, revision=row[1])


async def save_context_state(
    thread_key: str, segments: list[ConversationSummary], epoch_sequence: int, *, expected_revision: int
) -> bool:
    """把摘要状态写进会话行；失败向上抛，由调用方降级."""
    stmt = (
        update(ChatSession)
        .where(col(ChatSession.id) == thread_key, col(ChatSession.context_revision) == expected_revision)
        .values(context_state=serialize_state(segments, epoch_sequence), context_revision=expected_revision + 1)
        .returning(col(ChatSession.id))
    )
    async with get_async_session() as db:
        saved = (await db.execute(stmt)).first() is not None
    return saved


async def delete_thread_checkpoints(thread_id: str) -> bool:
    """删除某线程的 LangGraph checkpoint 三张表记录（best-effort）.

    Returns:
        全部删除成功为 True；表不存在或数据库错误为 False（调用方记日志即可）。
    """
    try:
        async with get_async_session() as db:
            await db.execute(_DELETE_CHECKPOINTS_SQL, {"thread_id": thread_id})
            await db.execute(_DELETE_BLOBS_SQL, {"thread_id": thread_id})
            await db.execute(_DELETE_WRITES_SQL, {"thread_id": thread_id})
        return True
    except Exception:
        # checkpoint 表可能尚未建（checkpointer.setup() 未跑过）：视为无孤儿可清
        logger.warning("thread_checkpoint_cleanup_skipped", thread_id=thread_id)
        return False
