"""数据库作为记忆版本的事实来源，工作账本保证增量与可恢复写入."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.database import async_engine, get_async_session
from app.models.semantic_memory import MemoryAccount, MemoryFact, MemoryWriteJob
from app.schemas.semantic_memory import MemoryOperation
from app.utils.clock import utc_now
from app.utils.memory_policy import key_hash, message_key


class MemoryConflictError(ValueError):
    """客户端读取的记忆版本已过期."""


class MemoryNotFoundError(ValueError):
    """条目不存在或不属于当前用户."""


class SemanticMemoryRepository:
    """所有内容查询限定用户，短事务内串行更新账户序号."""

    async def _lock(self, db: AsyncSession, user_id: int) -> MemoryAccount:
        now = utc_now()
        await db.execute(
            insert(MemoryAccount)
            .values(user_id=user_id, created_at=now, updated_at=now)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        row = await db.get(MemoryAccount, user_id, with_for_update=True)
        if row is None:
            raise MemoryNotFoundError("记忆账户不存在")
        return row

    async def account(self, user_id: int) -> MemoryAccount | None:
        """读取检索所需的当前代际和版本."""
        async with get_async_session() as db:
            return await db.get(MemoryAccount, user_id)

    async def stage(self, user_id: int, session_id: str, message_id: str, content: str) -> MemoryWriteJob | None:
        """重复来源消息复用原任务，已清除消息也不重新导入."""
        async with get_async_session() as db:
            account = await self._lock(db, user_id)
            if not account.enabled:
                return None
            existing = await db.scalar(
                select(MemoryWriteJob).where(
                    col(MemoryWriteJob.user_id) == user_id,
                    col(MemoryWriteJob.message_key) == message_key(session_id, message_id),
                )
            )
            if existing is not None:
                return existing
            account.sequence += 1
            account.updated_at = utc_now()
            job = MemoryWriteJob(
                user_id=user_id,
                message_key=message_key(session_id, message_id),
                source_session_id=session_id,
                source_message_id=message_id,
                sequence=account.sequence,
                generation=account.generation,
                text=content,
            )
            db.add(job)
            await db.flush()
            return job

    def _sync_job(self, db: AsyncSession, account: MemoryAccount) -> None:
        account.sequence += 1
        db.add(
            MemoryWriteJob(
                user_id=account.user_id,
                message_key=uuid4().hex,
                sequence=account.sequence,
                generation=account.generation,
                kind="SYNC",
            )
        )

    @asynccontextmanager
    async def worker_lock(self, user_id: int) -> AsyncIterator[bool]:
        """事务级咨询锁跨 API/worker 进程互斥，连接退出自动释放."""
        async with async_engine.connect() as connection:
            async with connection.begin():
                acquired = await connection.scalar(
                    text("SELECT pg_try_advisory_xact_lock(72841, :user_id)"), {"user_id": user_id}
                )
                yield bool(acquired)

    async def claim(self, user_id: int, lease_seconds: int) -> MemoryWriteJob | None:
        """只领取最早待办或已过期任务，禁止跨过仍在执行的任务."""
        async with get_async_session() as db:
            await self._lock(db, user_id)
            job = await db.scalar(
                select(MemoryWriteJob)
                .where(
                    col(MemoryWriteJob.user_id) == user_id,
                    col(MemoryWriteJob.status).in_(["PENDING", "RUNNING"]),
                )
                .order_by(col(MemoryWriteJob.sequence))
                .limit(1)
            )
            if job is None or (job.status == "RUNNING" and job.lease_until and job.lease_until > utc_now()):
                return None
            if job.attempts >= 3:
                job.status, job.error_code, job.lease_until = "FAILED", "RetryBudgetExceeded", None
                job.updated_at = utc_now()
                return None
            job.status, job.lease_until = "RUNNING", utc_now() + timedelta(seconds=lease_seconds)
            job.updated_at = utc_now()
            return job

    async def attempt(self, job_id: str, user_id: int) -> None:
        """尝试次数在调用外部模型前持久化，崩溃也计入预算."""
        async with get_async_session() as db:
            job = await db.get(MemoryWriteJob, job_id, with_for_update=True)
            if job and job.user_id == user_id and job.status == "RUNNING":
                job.attempts += 1
                job.updated_at = utc_now()

    async def apply(self, job_id: str, user_id: int, operations: list[MemoryOperation], event_days: int) -> bool:
        """先存事实与提取结果，索引重试不再重复提取或递增事实版本."""
        async with get_async_session() as db:
            account = await self._lock(db, user_id)
            job = await db.get(MemoryWriteJob, job_id, with_for_update=True)
            if job is None or job.user_id != user_id:
                raise MemoryNotFoundError("记忆任务不存在")
            if job.status != "RUNNING" or job.generation != account.generation or not account.enabled:
                if job.status == "RUNNING":
                    job.status, job.text, job.operations = "CANCELLED", None, None
                return False
            if job.operations is not None:
                return True
            for operation in operations:
                if operation.kind == "analysis_event" and not operation.memory_id:
                    operation = operation.model_copy(update={"key": message_key(job.message_key, operation.key)})
                if operation.memory_id:
                    fact = await db.get(MemoryFact, operation.memory_id)
                    if fact is None or fact.user_id != user_id:
                        raise MemoryNotFoundError("记忆条目不存在")
                    if fact.kind != operation.kind:
                        raise MemoryConflictError("记忆类型不匹配")
                else:
                    fact = await db.scalar(
                        select(MemoryFact).where(
                            col(MemoryFact.user_id) == user_id,
                            col(MemoryFact.key_hash) == key_hash(operation),
                        )
                    )
                if fact and fact.source_sequence > job.sequence:
                    continue
                if (
                    fact
                    and fact.status == "ACTIVE"
                    and operation.action == "upsert"
                    and fact.content == operation.content
                ):
                    # 同内容也推进来源序号，旧任务重试不能覆盖较新的确认。
                    fact.source_sequence = job.sequence
                    continue
                if fact is None:
                    fact = MemoryFact(user_id=user_id, key_hash=key_hash(operation), kind=operation.kind)
                    db.add(fact)
                else:
                    fact.version += 1
                fact.source_sequence, fact.generation = job.sequence, account.generation
                fact.index_state, fact.updated_at = "PENDING", utc_now()
                if operation.action == "delete":
                    self._erase(fact)
                else:
                    fact.status, fact.content, fact.source_quote = "ACTIVE", operation.content, operation.source_quote
                    fact.source_session_id, fact.source_message_id = job.source_session_id, job.source_message_id
                    fact.expires_at = (
                        utc_now() + timedelta(days=event_days) if operation.kind == "analysis_event" else None
                    )
                account.revision += 1
                # autoflush=False：后续同键操作必须看到本事务刚创建的事实。
                await db.flush()
            job.operations = [operation.model_dump() for operation in operations]
            job.updated_at = account.updated_at = utc_now()
            return True

    def _erase(self, fact: MemoryFact) -> None:
        fact.status, fact.content, fact.source_quote = "DELETED", None, None
        fact.source_session_id, fact.source_message_id = "", ""
        fact.expires_at = None

    async def facts(self, user_id: int, *, pending: bool = False, limit: int = 100) -> list[MemoryFact]:
        """普通读取排除过期事实，同步读取包含删除待办."""
        async with get_async_session() as db:
            query = select(MemoryFact).where(col(MemoryFact.user_id) == user_id)
            if pending:
                query = query.where(col(MemoryFact.index_state) == "PENDING")
            else:
                query = query.where(
                    col(MemoryFact.status) == "ACTIVE",
                    or_(
                        col(MemoryFact.expires_at).is_(None),
                        col(MemoryFact.expires_at) > utc_now(),
                    ),
                )
            return list(await db.scalars(query.order_by(col(MemoryFact.updated_at).desc()).limit(limit)))

    async def recalled(self, user_id: int, ids: list[str]) -> list[MemoryFact]:
        """召回校验只接受当前用户已就绪的有效事实."""
        async with get_async_session() as db:
            return list(
                await db.scalars(
                    select(MemoryFact).where(
                        col(MemoryFact.user_id) == user_id,
                        col(MemoryFact.id).in_(ids),
                        col(MemoryFact.status) == "ACTIVE",
                        col(MemoryFact.index_state) == "READY",
                        or_(col(MemoryFact.expires_at).is_(None), col(MemoryFact.expires_at) > utc_now()),
                    )
                )
            )

    async def indexed(self, fact: MemoryFact) -> None:
        """索引确认使用版本比较，不能确认已被纠正的旧快照."""
        async with get_async_session() as db:
            account = await self._lock(db, fact.user_id)
            current = await db.get(MemoryFact, fact.id, with_for_update=True)
            if current and current.version == fact.version and current.generation == fact.generation:
                current.index_state = "READY" if current.status == "ACTIVE" else "DELETED"
                account.revision += 1
                account.updated_at = utc_now()

    async def finish(self, job_id: str, user_id: int, status: str, error_code: str | None = None) -> None:
        """完成或取消后销毁输入正文，失败保留用于用户重试."""
        async with get_async_session() as db:
            job = await db.get(MemoryWriteJob, job_id, with_for_update=True)
            if job and job.user_id == user_id and job.status == "RUNNING":
                job.status, job.error_code, job.lease_until, job.updated_at = status, error_code, None, utc_now()
                if status != "FAILED":
                    job.text, job.operations = None, None

    async def ready_users(self) -> list[int]:
        """恢复调度只选有待办或过期租约的用户."""
        async with get_async_session() as db:
            return list(
                await db.scalars(
                    select(col(MemoryWriteJob.user_id))
                    .where(
                        or_(
                            col(MemoryWriteJob.status) == "PENDING",
                            (col(MemoryWriteJob.status) == "RUNNING") & (col(MemoryWriteJob.lease_until) < utc_now()),
                        )
                    )
                    .distinct()
                    .limit(20)
                )
            )

    async def jobs(self, user_id: int, limit: int = 20) -> list[MemoryWriteJob]:
        """按最新序号读取当前用户的任务账本."""
        async with get_async_session() as db:
            return list(
                await db.scalars(
                    select(MemoryWriteJob)
                    .where(
                        col(MemoryWriteJob.user_id) == user_id,
                    )
                    .order_by(col(MemoryWriteJob.sequence).desc())
                    .limit(limit)
                )
            )

    async def job(self, user_id: int, job_id: str) -> MemoryWriteJob:
        """每次重试读取已提交的提取载荷，不依赖进程内旧对象."""
        async with get_async_session() as db:
            job = await db.get(MemoryWriteJob, job_id)
            if job is None or job.user_id != user_id:
                raise MemoryNotFoundError("记忆任务不存在")
            return job

    async def retry(self, user_id: int, job_id: str) -> MemoryWriteJob:
        """显式人工重试开启新一轮有限预算，不改变原始顺序."""
        async with get_async_session() as db:
            account = await self._lock(db, user_id)
            job = await db.get(MemoryWriteJob, job_id, with_for_update=True)
            if job is None or job.user_id != user_id:
                raise MemoryNotFoundError("记忆任务不存在")
            if job.status != "FAILED" or job.generation != account.generation or not account.enabled:
                raise MemoryConflictError("任务不可重试，请刷新记忆状态")
            job.status, job.error_code, job.updated_at = "PENDING", None, utc_now()
            job.attempts = 0
            return job

    async def edit(self, user_id: int, fact_id: str, version: int, content: str | None) -> MemoryFact:
        """人工变更获得更高序号，旧失败任务不可覆盖."""
        async with get_async_session() as db:
            account = await self._lock(db, user_id)
            fact = await db.get(MemoryFact, fact_id, with_for_update=True)
            if fact is None or fact.user_id != user_id or fact.status != "ACTIVE":
                raise MemoryNotFoundError("记忆条目不存在")
            if fact.version != version:
                raise MemoryConflictError("记忆已变化，请重新读取")
            self._sync_job(db, account)
            fact.source_sequence, fact.version = account.sequence, fact.version + 1
            fact.generation, fact.index_state, fact.updated_at = account.generation, "PENDING", utc_now()
            if content is None:
                self._erase(fact)
            else:
                fact.content, fact.source_quote = content, content
                fact.source_session_id, fact.source_message_id = "", ""
            account.revision += 1
            account.updated_at = utc_now()
            return fact

    async def control(self, user_id: int, revision: int, *, enabled: bool | None = None) -> MemoryAccount:
        """清空或改变开关后，旧任务的代际永远失效，不能复活已删除文本."""
        async with get_async_session() as db:
            account = await self._lock(db, user_id)
            if account.revision != revision:
                raise MemoryConflictError("记忆状态已变化，请重新读取")
            if enabled is not None and enabled == account.enabled:
                return account
            account.generation += 1
            account.revision += 1
            if enabled is not None:
                account.enabled = enabled
            self._sync_job(db, account)
            account.updated_at = utc_now()
            facts = await db.scalars(select(MemoryFact).where(col(MemoryFact.user_id) == user_id))
            for fact in facts:
                fact.version += 1
                fact.source_sequence, fact.generation = account.sequence, account.generation
                fact.index_state, fact.updated_at = "PENDING", utc_now()
                if enabled is None:
                    self._erase(fact)
            jobs = await db.scalars(
                select(MemoryWriteJob).where(
                    col(MemoryWriteJob.user_id) == user_id,
                    col(MemoryWriteJob.kind) == "EXTRACT",
                    col(MemoryWriteJob.generation) < account.generation,
                )
            )
            for job in jobs:
                job.text, job.operations = None, None
                job.source_session_id, job.source_message_id = "", ""
                if job.status in {"PENDING", "RUNNING", "FAILED"}:
                    job.status, job.lease_until = "CANCELLED", None
                job.updated_at = utc_now()
            return account


semantic_memory_repository = SemanticMemoryRepository()
