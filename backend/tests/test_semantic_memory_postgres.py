"""真实 PostgreSQL 验证幂等账本、版本治理及 worker 重试，所有测试用户回滚."""

import asyncio
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from mem0.vector_stores.pgvector import PGVector
from psycopg.conninfo import make_conninfo

from app.core import database
from app.core.config import settings
from app.models.semantic_memory import MemoryFact, MemoryWriteJob
from app.models.user import User
from app.integrations.memory_index import search_index, sync_fact
from app.repositories.semantic_memory_repository import (
    MemoryConflictError,
    MemoryNotFoundError,
    semantic_memory_repository as repo,
)
from app.schemas.semantic_memory import MemoryOperation
from app.services.memory import MemoryService
from app.utils.clock import utc_now

pytestmark = pytest.mark.skipif(os.getenv("FUND_TEST_POSTGRES") != "true", reason="requires PostgreSQL opt-in")


@pytest.fixture
async def memory_database(monkeypatch):
    async with database.async_engine.connect() as connection:
        outer = await connection.begin()
        try:

            def factory():
                return AsyncSession(
                    bind=connection, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint"
                )

            monkeypatch.setattr(database, "async_session_factory", factory)
            async with database.get_async_session() as db:
                users = [
                    User(
                        email=f"memory-{uuid4()}@example.invalid",
                        hashed_password="fixture-not-login",  # pragma: allowlist secret -- inert fixture
                    )
                    for _ in range(2)
                ]
                db.add_all(users)
                await db.flush()
                ids = [user.id for user in users]
            yield ids
        finally:
            await outer.rollback()
            await database.async_engine.dispose()


def operation(content="比较基金时优先看回撤", memory_id=None):
    return MemoryOperation(
        kind="research_preference", key="compare_drawdown", content=content, source_quote=content, memory_id=memory_id
    )


async def _fact(user_id, message="message"):
    job = await repo.stage(user_id, "s", message, "比较基金时优先看回撤")
    assert job is not None
    await repo.claim(user_id, 300)
    assert await repo.apply(job.id, user_id, [operation()], 180)
    fact = (await repo.facts(user_id))[0]
    await repo.indexed(fact)
    await repo.finish(job.id, user_id, "SUCCEEDED")
    return (await repo.facts(user_id))[0], job


async def test_stage_idempotent_per_source_and_empty_after_success(memory_database):
    owner, other = memory_database
    first = await repo.stage(owner, "s", "m", "比较基金时优先看回撤")
    repeated = await repo.stage(owner, "s", "m", "另一份请求文本")
    distinct = await repo.stage(owner, "s", "new-m", "比较基金时优先看回撤")
    assert first and repeated and distinct
    assert first.id == repeated.id and distinct.id != first.id
    assert first.sequence < distinct.sequence
    assert await repo.jobs(other) == []
    await repo.claim(owner, 300)
    await repo.finish(first.id, owner, "SUCCEEDED")
    done = (await repo.jobs(owner))[1]
    assert done.text is None and done.operations is None


async def test_corrected_fact_stale_retry_cannot_overwrite_and_cross_user_rejected(memory_database):
    owner, other = memory_database
    fact, _ = await _fact(owner)
    delayed = await repo.stage(owner, "s", "delayed", "错误地偏好费用")
    assert delayed
    await repo.claim(owner, 300)
    await repo.finish(delayed.id, owner, "FAILED", "TimeoutError")
    with pytest.raises(MemoryNotFoundError):
        await repo.edit(other, fact.id, 1, "研究费用")
    with pytest.raises(MemoryNotFoundError):
        await repo.retry(other, delayed.id)
    await repo.edit(owner, fact.id, 1, "比较基金时优先看费用")
    with pytest.raises(MemoryConflictError):
        await repo.edit(owner, fact.id, 1, "过期编辑")
    # 人工纠错还未完成向量索引，旧版本立即失去召回资格。
    assert not await repo.recalled(owner, [fact.id])
    await repo.retry(owner, delayed.id)
    claimed = await repo.claim(owner, 300)
    assert claimed and claimed.id == delayed.id
    assert await repo.apply(delayed.id, owner, [operation("错误地偏好费用", fact.id)], 180)
    current = (await repo.facts(owner))[0]
    assert current.content == "比较基金时优先看费用" and current.version == 2
    await repo.indexed(fact)  # 旧索引确认不能把已修改版本标 READY。
    assert not await repo.recalled(owner, [fact.id])


async def test_clear_cancels_inflight_and_replayed_source_does_not_resurrect(memory_database):
    owner, _ = memory_database
    fact, _ = await _fact(owner)
    pending = await repo.stage(owner, "s", "pending", "研究费用")
    assert pending
    await repo.claim(owner, 300)
    account = await repo.account(owner)
    assert account
    await repo.control(owner, account.revision)
    assert not await repo.apply(pending.id, owner, [operation("研究费用")], 180)
    replayed = await repo.stage(owner, "s", "pending", "研究费用")
    assert replayed and replayed.id == pending.id and replayed.status == "CANCELLED"
    assert replayed.text is None and replayed.operations is None
    assert await repo.facts(owner) == [] and await repo.recalled(owner, [fact.id]) == []
    tombstone = (await repo.facts(owner, pending=True))[0]
    assert tombstone.status == "DELETED" and tombstone.content is None and tombstone.source_quote is None


async def test_disable_blocks_add_and_inflight_then_enable_reindexes(memory_database):
    owner, _ = memory_database
    fact, _ = await _fact(owner)
    account = await repo.account(owner)
    assert account
    disabled = await repo.control(owner, account.revision, enabled=False)
    assert not disabled.enabled and await repo.stage(owner, "s", "new", "研究费用") is None
    assert (await repo.facts(owner))[0].content == fact.content
    enabled = await repo.control(owner, disabled.revision, enabled=True)
    assert enabled.enabled and enabled.generation > disabled.generation
    current = (await repo.facts(owner))[0]
    assert current.index_state == "PENDING" and current.version > fact.version


async def test_expired_memory_is_never_recalled(memory_database):
    owner, _ = memory_database
    fact, _ = await _fact(owner)
    async with database.get_async_session() as db:
        row = await db.get(MemoryFact, fact.id)
        assert row
        row.expires_at = utc_now() - timedelta(seconds=1)
    assert await repo.facts(owner) == []
    assert await repo.recalled(owner, [fact.id]) == []


async def test_expired_lease_recovered_and_retry_budget_persists(memory_database):
    owner, _ = memory_database
    job = await repo.stage(owner, "s", "m", "研究回撤")
    assert job
    await repo.claim(owner, 300)
    assert await repo.claim(owner, 300) is None
    for _ in range(3):
        await repo.attempt(job.id, owner)
    async with database.get_async_session() as db:
        current = await db.get(MemoryWriteJob, job.id)
        assert current
        current.lease_until = utc_now() - timedelta(seconds=1)
    assert owner in await repo.ready_users()
    assert await repo.claim(owner, 300) is None
    failed = (await repo.jobs(owner))[0]
    assert failed.status == "FAILED" and failed.attempts == 3
    retried = await repo.retry(owner, job.id)
    assert retried.attempts == 0
    assert await repo.claim(owner, 300)


async def test_worker_retries_index_without_reextracting_and_keeps_failed_jobs_visible(memory_database, monkeypatch):
    owner, _ = memory_database
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", True)
    service = MemoryService(repo)
    extractor = SimpleNamespace(
        generate_response=lambda **kwargs: json.dumps({"operations": [operation().model_dump()]})
    )
    service._memory = SimpleNamespace(llm=extractor)
    monkeypatch.setattr("app.services.memory.enqueue", AsyncMock())
    sync = AsyncMock(side_effect=[ConnectionError("index failed"), None])
    monkeypatch.setattr("app.services.memory.sync_fact", sync)
    extraction = AsyncMock(wraps=service._extract)
    monkeypatch.setattr(service, "_extract", extraction)
    assert (
        await service.add(
            str(owner), [{"role": "user", "id": "first", "content": "比较基金时优先看回撤"}], {"session_id": "s"}
        )
        == "queued"
    )
    await service.process_user(owner)
    jobs = await repo.jobs(owner)
    assert jobs[0].status == "SUCCEEDED" and jobs[0].attempts == 2 and jobs[0].text is None
    assert extraction.await_count == 1 and sync.await_count == 2
    assert (await repo.facts(owner))[0].version == 1
    extractor.generate_response = lambda **kwargs: "invalid JSON"
    await service.add(
        str(owner), [{"role": "user", "id": "second", "content": "比较基金时优先看费用"}], {"session_id": "s"}
    )
    await service.process_user(owner)
    failed = (await repo.jobs(owner))[0]
    assert failed.status == "FAILED" and failed.attempts == 3 and failed.text
    assert failed.error_code == "ValidationError"


async def test_advisory_lock_excludes_second_worker_and_releases(memory_database):
    owner, _ = memory_database
    async with repo.worker_lock(owner) as first:
        assert first
        async with repo.worker_lock(owner) as second:
            assert not second
    async with repo.worker_lock(owner) as released:
        assert released


async def test_duplicate_keys_in_one_extraction_reuse_fact_and_distinct_events_keep_separate(memory_database):
    owner, _ = memory_database
    job = await repo.stage(owner, "s", "m", "比较基金时优先看回撤，也优先看费用")
    assert job
    await repo.claim(owner, 300)
    await repo.apply(job.id, owner, [operation(), operation("也优先看费用")], 180)
    facts = await repo.facts(owner)
    assert len(facts) == 1 and facts[0].content == "也优先看费用"
    await repo.finish(job.id, owner, "SUCCEEDED")
    for message_id in ["event-1", "event-2"]:
        event = await repo.stage(owner, "s", message_id, "上次我比较过两只基金")
        assert event
        await repo.claim(owner, 300)
        await repo.apply(
            event.id,
            owner,
            [
                MemoryOperation(
                    kind="analysis_event",
                    key="comparison",
                    content="上次我比较过两只基金",
                    source_quote="上次我比较过两只基金",
                )
            ],
            180,
        )
        await repo.finish(event.id, owner, "SUCCEEDED")
    assert len(await repo.facts(owner)) == 3


async def test_committed_extraction_acknowledgement_loss_does_not_reextract(memory_database, monkeypatch):
    owner, _ = memory_database
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", True)
    service = MemoryService(repo)
    service._memory = SimpleNamespace(
        llm=SimpleNamespace(generate_response=lambda **kwargs: json.dumps({"operations": [operation().model_dump()]}))
    )
    monkeypatch.setattr("app.services.memory.sync_fact", AsyncMock())
    original = repo.apply
    calls = 0

    async def apply(*args):
        nonlocal calls
        result = await original(*args)
        calls += 1
        if calls == 1:
            raise ConnectionError("commit acknowledgement lost")
        return result

    monkeypatch.setattr(repo, "apply", apply)
    extractor = AsyncMock(wraps=service._extract)
    monkeypatch.setattr(service, "_extract", extractor)
    await repo.stage(owner, "s", "m", "比较基金时优先看回撤")
    await service.process_user(owner)
    assert extractor.await_count == 1 and calls == 1
    assert (await repo.jobs(owner))[0].status == "SUCCEEDED"


async def test_native_pgvector_sdk_contract_and_database_validated_recall(memory_database, monkeypatch):
    owner, _ = memory_database
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", True)
    store = await asyncio.to_thread(
        PGVector,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        collection_name=settings.LONG_TERM_MEMORY_COLLECTION_NAME,
        embedding_model_dims=settings.EMBEDDING_DIM,
        diskann=False,
        hnsw=False,
        minconn=1,
        maxconn=1,
        connection_string=make_conninfo(
            dbname=settings.POSTGRES_DB,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host=settings.POSTGRES_HOST,
            port=str(settings.POSTGRES_PORT),
            connect_timeout="5",
            options="-c statement_timeout=2000 -c lock_timeout=1000",
        ),
    )
    memory = SimpleNamespace(
        vector_store=store,
        embedding_model=SimpleNamespace(embed=lambda *args: [1.0] + [0.0] * (settings.EMBEDDING_DIM - 1)),
    )
    fact, _ = await _fact(owner)
    service = MemoryService(repo)
    service._memory = memory
    monkeypatch.setattr(
        "app.services.memory.cache_service", SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    )
    try:
        await sync_fact(memory, fact)
        await repo.edit(owner, fact.id, fact.version, "比较基金时优先看费用")
        fact = (await repo.facts(owner))[0]
        await sync_fact(memory, fact)
        await repo.indexed(fact)
        result = await search_index(memory, query="我的研究偏好", user_id=str(owner), generation=fact.generation)
        assert len(result["results"]) == 1
        row = result["results"][0]
        assert abs(row["score"]) < 0.0001 and row["metadata"]["fact_version"] == 2
        assert row["metadata"]["fact_id"] == fact.id
        assert "优先看费用" in await service.search(str(owner), "我的研究偏好")
        await repo.edit(owner, fact.id, fact.version, None)
        assert await service.search(str(owner), "我的研究偏好") == ""
        fact = (await repo.facts(owner, pending=True))[0]
        await sync_fact(memory, fact)
        assert await asyncio.to_thread(store.get, vector_id=fact.id) is None
    finally:
        await asyncio.to_thread(store.delete, vector_id=fact.id)
        await asyncio.to_thread(store.connection_pool.close)
