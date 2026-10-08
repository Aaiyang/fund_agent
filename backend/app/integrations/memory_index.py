"""mem0 1.0 的 pgvector 索引适配；数据库事实负责内容、版本和删除权限."""

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any

from mem0 import AsyncMemory

from app.models.semantic_memory import MemoryFact

MANAGED_BY = "fund_agent_memory_v2"


async def search_index(memory: AsyncMemory, *, query: str, user_id: str, generation: int, limit: int = 20) -> dict:
    """锁定 SDK 的 AsyncMemory.search 缺失过滤方法，直接组合其 embedding/pgvector 接口."""
    vector = await asyncio.to_thread(memory.embedding_model.embed, query, "search")
    rows = await asyncio.to_thread(
        memory.vector_store.search,
        query=query,
        vectors=vector,
        limit=limit,
        filters={"user_id": user_id, "managed_by": MANAGED_BY, "generation": generation},
    )
    return {"results": [{"id": row.id, "score": row.score, "metadata": row.payload or {}} for row in rows]}


async def _write_index(operation: Callable[..., Any], **kwargs: Any) -> None:
    """超时/取消时等已发出的 DB 写结束，再释放 worker 锁，避免后台旧写覆盖新索引."""
    task = asyncio.create_task(asyncio.to_thread(operation, **kwargs))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


async def sync_fact(memory: AsyncMemory, fact: MemoryFact) -> None:
    """固定向量 ID 幂等覆盖，不产生额外 SQLite 记忆历史或随机重复向量."""
    existing = await asyncio.to_thread(memory.vector_store.get, vector_id=fact.id)
    if existing and (
        existing.payload.get("user_id") != str(fact.user_id) or existing.payload.get("managed_by") != MANAGED_BY
    ):
        raise ValueError("memory vector ownership mismatch")
    if fact.status == "DELETED":
        if existing:
            await _write_index(memory.vector_store.delete, vector_id=fact.id)
        return
    if not fact.content:
        raise ValueError("active memory has no content")
    vector = await asyncio.to_thread(memory.embedding_model.embed, fact.content, "add")
    payload = {
        "data": fact.content,
        "hash": hashlib.sha256(fact.content.encode()).hexdigest(),
        "user_id": str(fact.user_id),
        "managed_by": MANAGED_BY,
        "fact_id": fact.id,
        "fact_version": fact.version,
        "generation": fact.generation,
        "created_at": fact.created_at.isoformat(),
        "updated_at": fact.updated_at.isoformat(),
    }
    if existing is None:
        await _write_index(memory.vector_store.insert, vectors=[vector], ids=[fact.id], payloads=[payload])
    else:
        await _write_index(memory.vector_store.update, vector_id=fact.id, vector=vector, payload=payload)
