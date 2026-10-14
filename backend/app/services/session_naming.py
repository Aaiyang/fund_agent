"""会话自动命名.

新会话的第一条消息进来时，本模块按下面三步走：
  1. 在 Postgres 上原子地认领这个会话。有了这一步，并发的多个请求之间、
     多个 uvicorn worker 之间，都不会把同一次命名重复调一遍 LLM。
  2. 先从用户消息里截出一个占位名写上去，这样即使后面那次 LLM 调用失败，
     会话列表里也不会剩下空白名字。
  3. 再挂一个后台 asyncio 任务，用快的 nano 模型带结构化输出生成正式标题，
     生成成功后覆盖掉占位名。
"""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from sqlmodel import (
    col,
    update,
)

from app.core.database import get_async_session
from app.core.logging import logger
from app.core.metrics import session_names_generated_total
from app.agent.prompts import SESSION_TITLE_PROMPT
from app.models.session import Session as ChatSession
from app.schemas.chat import SessionTitle
from app.services.database import database_service
from app.services.llm import llm_service

_PLACEHOLDER_MAX = 40

_background_tasks: set[asyncio.Task] = set()


def _build_placeholder(user_message: str) -> str:
    cleaned = " ".join(user_message.split())
    return cleaned[:_PLACEHOLDER_MAX].rstrip() or "New chat"


async def _claim_session(session_id: str, placeholder: str) -> bool:
    """本次调用抢到那个原子的 Postgres 认领时返回 True.

    一条 `UPDATE … WHERE name = ''` 一次往返就完成，所以并发的多个调用者里
    恰好只有一个能拿到 rowcount == 1。
    """
    async with get_async_session() as db:
        stmt = (
            update(ChatSession)
            .where(col(ChatSession.id) == session_id, col(ChatSession.name) == "")
            .values(name=placeholder)
        )
        result = await db.execute(stmt)
        return (result.rowcount or 0) == 1


async def _persist_session_name(session_id: str, user_message: str) -> None:
    try:
        result = await llm_service.call(
            [
                SystemMessage(content=SESSION_TITLE_PROMPT),
                HumanMessage(content=user_message[:500]),
            ],
            response_format=SessionTitle,
            max_tokens=32,
            temperature=0.3,
        )
        await database_service.update_session_name(session_id, result.title)
        session_names_generated_total.labels(status="success").inc()
        logger.info("session_name_generated", session_id=session_id, name=result.title)
    except Exception:
        session_names_generated_total.labels(status="error").inc()
        logger.exception("session_name_generation_failed", session_id=session_id)


async def maybe_name_session(session_id: str, session_name: str, messages: list) -> None:
    """会话还没名字时，触发自动命名.

    任何聊天端点都可以直接调它——同一个会话的并发调用会被前面那步
    Postgres 原子认领去重，最终只生效一次。
    """
    if session_name:
        return
    first_user_msg = next((m.content for m in messages if m.role == "user"), None)
    if not first_user_msg:
        return
    if await _claim_session(session_id, _build_placeholder(first_user_msg)):
        task = asyncio.create_task(_persist_session_name(session_id, first_user_msg))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
