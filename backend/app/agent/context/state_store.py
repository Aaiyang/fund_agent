"""会话线程状态的数据库持久化：摘要段 + LangGraph checkpoint 清理.

摘要段与 Cache Epoch 存在 ``session.context_state``（JSON 列）上——
随会话行存亡：删除会话即删除状态，天然按用户（session.user_id）隔离。
ContextManager 进程内的字典仍是主存储（读穿缓存），本模块负责
进程重启后的恢复与压缩后的落盘。

同时提供 ``delete_thread_checkpoints``：删除会话时顺手清掉 LangGraph
checkpointer 在同一库里的三张表，避免对话内容成为孤儿。
"""

from sqlalchemy import text
from sqlmodel import col, select, update

from app.agent.context.models import ConversationSummary
from app.core.database import get_async_session
from app.core.logging import logger
from app.models.session import Session as ChatSession

_STATE_VERSION = 1

_DELETE_CHECKPOINTS_SQL = text("DELETE FROM checkpoints WHERE thread_id = :thread_id")
_DELETE_BLOBS_SQL = text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id")
_DELETE_WRITES_SQL = text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id")


def serialize_state(segments: list[ConversationSummary], epoch_sequence: int) -> dict:
    """把摘要段与 Epoch 序号打包成可入库的 JSON 载荷（datetime 安全）."""
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
    except Exception:
        # 单段损坏视为整体不可信：进程内会重新压缩
        logger.warning("context_state_payload_invalid")
        return None
    return segments, sequence


async def load_context_state(thread_key: str) -> tuple[list[ConversationSummary], int] | None:
    """读取某会话的落盘状态；行不存在或载荷无效返回 None."""
    stmt = select(ChatSession.context_state).where(col(ChatSession.id) == thread_key)
    async with get_async_session() as db:
        row = (await db.execute(stmt)).first()
    payload = row[0] if row else None
    return parse_state(payload)


async def save_context_state(thread_key: str, segments: list[ConversationSummary], epoch_sequence: int) -> None:
    """把摘要状态写进会话行；失败向上抛，由调用方降级."""
    stmt = (
        update(ChatSession)
        .where(col(ChatSession.id) == thread_key)
        .values(context_state=serialize_state(segments, epoch_sequence))
    )
    async with get_async_session() as db:
        await db.execute(stmt)


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
