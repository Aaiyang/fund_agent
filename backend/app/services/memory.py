"""基于 mem0 + pgvector 的长期记忆服务，查询结果外面可选套一层缓存."""

import asyncio
import json

import tiktoken
from langfuse import get_client, observe
from mem0 import AsyncMemory
from mem0.utils.factory import EmbedderFactory
from psycopg.conninfo import make_conninfo
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from app.core.cache import (
    cache_key,
    cache_service,
)
from app.core.config import settings
from app.core.logging import logger
from app.agent.prompts import load_prompt_file
from app.core.metrics import (
    memory_candidates_rejected_total,
    memory_jobs_total,
    memory_retrieval_seconds,
    memory_retrieval_total,
    memory_write_seconds,
)
from app.core.task_queue import enqueue
from app.integrations.memory_index import MANAGED_BY, search_index, sync_fact
from app.models.semantic_memory import MemoryAccount, MemoryWriteJob
from app.repositories.semantic_memory_repository import SemanticMemoryRepository, semantic_memory_repository
from app.schemas.semantic_memory import MemoryExtraction, MemoryItemOut, MemoryJobOut, MemorySettingsOut
from app.utils.clock import business_today
from app.utils.memory_policy import allowed_text, should_extract, should_retrieve, validate_operation
from app.workers import MEMORY_WRITE_TASK


OPENAI_COMPATIBLE_EMBEDDER = "app.services.embeddings.OpenAICompatibleEmbedding"
_EXTRACTION_PROMPT = load_prompt_file("memory_extraction.md")
_ENCODER = tiktoken.get_encoding("cl100k_base")


class MemoryExtractionError(ValueError):
    """供应商或提取错误仅保留类别，避免日志/追踪记录原文."""


class MemoryService:
    """数据库管理事实与任务，mem0 管理 embedding 与语义索引."""

    def __init__(self, repository: SemanticMemoryRepository = semantic_memory_repository):
        """只置空实例：真正的 AsyncMemory 延到首次使用时再构建."""
        self._memory: AsyncMemory | None = None
        self.repository = repository
        self._init_lock = asyncio.Lock()

    async def _get_memory(self) -> AsyncMemory:
        async with self._init_lock:
            return await self._create_memory()

    async def _create_memory(self) -> AsyncMemory:
        if self._memory is None:
            embedder_provider = settings.EMBEDDING_PROVIDER
            if settings.EMBEDDING_PROVIDER in {"openai", "openai_compatible"}:
                embedder_provider = "openai"
                EmbedderFactory.provider_to_class[embedder_provider] = OPENAI_COMPATIBLE_EMBEDDER

            llm_config = {
                "model": settings.LONG_TERM_MEMORY_MODEL,
                "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                "api_key": settings.OPENAI_API_KEY,
                "max_tokens": settings.MEMORY_EXTRACTION_MAX_TOKENS,
            }
            if settings.LLM_PROVIDER == "deepseek":
                llm_config["deepseek_base_url"] = settings.OPENAI_BASE_URL
            else:
                llm_config["openai_base_url"] = settings.OPENAI_BASE_URL

            self._memory = await AsyncMemory.from_config(
                config_dict={
                    "vector_store": {
                        "provider": "pgvector",
                        "config": {
                            "collection_name": settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                            "dbname": settings.POSTGRES_DB,
                            "user": settings.POSTGRES_USER,
                            "password": settings.POSTGRES_PASSWORD,
                            "host": settings.POSTGRES_HOST,
                            "port": settings.POSTGRES_PORT,
                            "embedding_model_dims": settings.EMBEDDING_DIM,
                            "connection_string": make_conninfo(
                                dbname=settings.POSTGRES_DB,
                                user=settings.POSTGRES_USER,
                                password=settings.POSTGRES_PASSWORD,
                                host=settings.POSTGRES_HOST,
                                port=str(settings.POSTGRES_PORT),
                                connect_timeout="5",
                                options="-c statement_timeout=2000 -c lock_timeout=1000",
                            ),
                        },
                    },
                    "llm": {
                        "provider": settings.LLM_PROVIDER,
                        "config": llm_config,
                    },
                    "embedder": {
                        "provider": embedder_provider,
                        "config": {
                            "model": settings.LONG_TERM_MEMORY_EMBEDDER_MODEL,
                            "api_key": settings.EMBEDDING_API_KEY,
                            "openai_base_url": settings.EMBEDDING_BASE_URL,
                            "embedding_dims": settings.EMBEDDING_DIM,
                        },
                    },
                }
            )
            client = getattr(self._memory.llm, "client", None)
            if client is not None and hasattr(client, "with_options"):
                self._memory.llm.client = client.with_options(
                    timeout=settings.MEMORY_WRITE_TIMEOUT_SECONDS, max_retries=0
                )
        return self._memory

    async def initialize(self) -> None:
        """预先把 mem0 的 AsyncMemory 实例连同它的 pgvector 连接池一起暖好.

        只在启动时调一次，好让第一次 search() 或 worker 不必承担
        `from_config` + `pgvector.list_cols()` 那约 130ms 的冷启动开销。
        """
        if not settings.LONG_TERM_MEMORY_ENABLED:
            logger.info("memory_service_disabled")
            return

        await self._get_memory()
        logger.info("memory_service_initialized")

    async def close(self) -> None:
        """显式释放 SDK 主索引、辅助索引、客户端及 SQLite 资源，不依赖解释器析构."""
        memory, self._memory = self._memory, None
        if memory is None:
            return
        resources = [
            getattr(memory.vector_store, "connection_pool", None),
            getattr(getattr(memory, "_telemetry_vector_store", None), "connection_pool", None),
            getattr(memory.embedding_model, "client", None),
            getattr(memory.llm, "client", None),
            getattr(memory, "db", None),
        ]
        closed: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in closed:
                continue
            closed.add(id(resource))
            closer = getattr(resource, "close", None) or getattr(resource, "closeall", None)
            if callable(closer):
                try:
                    await asyncio.to_thread(closer)
                except Exception:
                    logger.exception("memory_resource_close_failed")

    async def search(self, user_id: str | None, query: str) -> str:
        """检索该用户与 query 相关的长期记忆.

        先查缓存，未命中才去问 mem0，并把结果写回缓存。

        返回拼装好的记忆文本；查询失败时返回空串，没给 user_id 时同样返回
        空串——匿名会话一律跳过长期记忆，而不是把这些人混进同一个共享分区。
        """
        if not settings.LONG_TERM_MEMORY_ENABLED or user_id is None or not should_retrieve(query):
            return ""
        try:
            with memory_retrieval_seconds.time():
                async with asyncio.timeout(settings.MEMORY_SEARCH_TIMEOUT_SECONDS):
                    return await self._search(int(user_id), query)
        except Exception as exc:
            memory_retrieval_total.labels(status="failed").inc()
            logger.warning("memory_retrieval_failed", user_id=user_id, error_code=type(exc).__name__)
            return ""

    async def _search(self, user_id: int, query: str) -> str:
        account = await self.repository.account(user_id)
        if account is None or not account.enabled:
            return ""
        key = cache_key("memory:v2", str(user_id), str(account.generation), str(account.revision), query)
        cached = None
        try:
            cached = await cache_service.get(key)
        except Exception:
            logger.exception("memory_cache_read_failed")
        if cached is not None:
            entries = json.loads(cached)
            facts = {
                fact.id: fact for fact in await self.repository.recalled(user_id, [entry["id"] for entry in entries])
            }
            valid = all(
                entry["id"] in facts
                and facts[entry["id"]].generation == account.generation
                and facts[entry["id"]].version == entry["version"]
                for entry in entries
            )
            current = await self.repository.account(user_id)
            if valid and current and current.enabled and current.revision == account.revision:
                memory_retrieval_total.labels(status="cached").inc()
                return cached
            if current is None or not current.enabled or current.revision != account.revision:
                return ""
        memory = await self._get_memory()
        results = await search_index(
            memory,
            query=query,
            user_id=str(user_id),
            limit=20,
            generation=account.generation,
        )
        # pgvector 返回的是余弦距离（越小越相近），不能使用 mem0 通用的 >= threshold。
        candidates: dict[str, dict] = {}
        for item in sorted(results["results"], key=lambda item: float(item.get("score", 2))):
            metadata = item.get("metadata") or {}
            score = item.get("score")
            if metadata.get("managed_by") != MANAGED_BY or metadata.get("generation") != account.generation:
                continue
            if score is None or not 0 <= float(score) <= settings.MEMORY_SEARCH_MAX_DISTANCE:
                continue
            candidates.setdefault(metadata.get("fact_id", ""), metadata)
        facts = {fact.id: fact for fact in await self.repository.recalled(user_id, list(candidates))}
        selected: list[dict] = []
        for fact_id, metadata in candidates.items():
            fact = facts.get(fact_id)
            if fact is None or fact.generation != account.generation or fact.version != metadata.get("fact_version"):
                continue
            entry = {
                "id": fact.id,
                "kind": fact.kind,
                "content": fact.content,
                "version": fact.version,
                "observed_at": fact.updated_at.isoformat(),
            }
            proposed = json.dumps(selected + [entry], ensure_ascii=False)
            if len(_ENCODER.encode(proposed)) > settings.MEMORY_CONTEXT_TOKEN_BUDGET:
                continue
            selected.append(entry)
            if len(selected) >= settings.MEMORY_SEARCH_TOP_K:
                break
        current = await self.repository.account(user_id)
        if current is None or not current.enabled or current.revision != account.revision:
            return ""
        result = json.dumps(selected, ensure_ascii=False) if selected else ""
        memory_retrieval_total.labels(status="hit" if result else "empty").inc()
        if result:
            try:
                await cache_service.set(key, result)
            except Exception:
                logger.exception("memory_cache_write_failed")
        return result

    async def add(self, user_id: str | None, messages: list[dict], metadata: dict | None = None) -> str:
        """同步登记真实用户消息；外部提取和向量写入由持久化任务执行."""
        if not settings.LONG_TERM_MEMORY_ENABLED or user_id is None:
            return "disabled"
        session_id = str((metadata or {}).get("session_id") or "")
        users = [message for message in messages if message.get("role") == "user"]
        if not users or not session_id:
            return "skipped"
        message = users[-1]
        content, message_id = message.get("content"), message.get("id")
        if (
            not isinstance(content, str)
            or not message_id
            or len(content) > settings.MEMORY_INPUT_MAX_CHARS
            or not should_extract(content)
        ):
            return "skipped"
        try:
            async with asyncio.timeout(settings.MEMORY_STAGE_TIMEOUT_SECONDS):
                job = await self.repository.stage(int(user_id), session_id, str(message_id), content)
            if job is None:
                return "disabled"
            if job.status == "PENDING":
                await self.dispatch(int(user_id))
            return "queued" if job.status in {"PENDING", "RUNNING"} else job.status.lower()
        except Exception as exc:
            logger.warning("memory_stage_failed", user_id=user_id, error_code=type(exc).__name__)
            return "unavailable"

    async def dispatch(self, user_id: int) -> None:
        """入队失败保留数据库待办，由独立恢复循环再次投递."""
        try:
            async with asyncio.timeout(2):
                await enqueue(MEMORY_WRITE_TASK, user_id=user_id)
        except Exception:
            # 已提交的账本保留 PENDING，调度器恢复；不把排队失败当成丢失消息。
            logger.exception("memory_dispatch_failed", user_id=user_id)

    @observe(name="memory_fact_extraction", as_type="generation", capture_input=False, capture_output=False)
    async def _extract(self, memory: AsyncMemory, job: MemoryWriteJob) -> MemoryExtraction:
        if settings.LANGFUSE_TRACING_ENABLED:
            get_client().update_current_generation(
                model=settings.LONG_TERM_MEMORY_MODEL, metadata={"job_id": job.id, "user_id": str(job.user_id)}
            )
        facts = await self.repository.facts(job.user_id, limit=30)
        payload = {
            "user_message": job.text,
            "message_id": job.source_message_id,
            "business_date": business_today().isoformat(),
            "existing_memories": [{"id": fact.id, "kind": fact.kind, "content": fact.content} for fact in facts],
        }
        try:
            response = await asyncio.to_thread(
                memory.llm.generate_response,
                messages=[
                    {"role": "system", "content": _EXTRACTION_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
            )
            extraction = MemoryExtraction.model_validate_json(response)
        except Exception as exc:
            raise MemoryExtractionError(type(exc).__name__) from None
        valid = [operation for operation in extraction.operations if validate_operation(operation, job.text or "")]
        memory_candidates_rejected_total.inc(len(extraction.operations) - len(valid))
        return MemoryExtraction(operations=valid)

    async def process_user(self, user_id: int) -> None:
        """按用户序号执行；进程崩溃由租期恢复，单次失败最多重试三次."""
        if not settings.LONG_TERM_MEMORY_ENABLED:
            return
        async with self.repository.worker_lock(user_id) as acquired:
            if not acquired:
                return
            for _ in range(10):
                job = await self.repository.claim(user_id, settings.MEMORY_WRITE_TIMEOUT_SECONDS * 3 + 60)
                if job is None:
                    return
                try:
                    status = "FAILED"
                    with memory_write_seconds.time():
                        async for attempt in AsyncRetrying(
                            stop=stop_after_attempt(max(1, 3 - job.attempts)),
                            wait=wait_exponential(multiplier=1, min=1, max=4),
                            reraise=True,
                        ):
                            with attempt:
                                await self.repository.attempt(job.id, user_id)
                                async with asyncio.timeout(settings.MEMORY_WRITE_TIMEOUT_SECONDS):
                                    status = await self._process_job(job)
                    await self.repository.finish(job.id, user_id, status)
                    memory_jobs_total.labels(status=status.lower()).inc()
                except Exception as exc:
                    error_code = str(exc) if isinstance(exc, MemoryExtractionError) else type(exc).__name__
                    await self.repository.finish(job.id, user_id, "FAILED", error_code)
                    memory_jobs_total.labels(status="failed").inc()
                    logger.warning("memory_write_failed", user_id=user_id, job_id=job.id, error_code=error_code)

    async def _process_job(self, job: MemoryWriteJob) -> str:
        job = await self.repository.job(job.user_id, job.id)
        if job.status != "RUNNING":
            return "CANCELLED"
        account = await self.repository.account(job.user_id)
        if account is None or (
            job.kind == "EXTRACT" and (not account.enabled or job.generation != account.generation)
        ):
            return "CANCELLED"
        memory = await self._get_memory()
        if job.kind == "EXTRACT":
            if job.operations is None:
                extraction = await self._extract(memory, job)
                if not await self.repository.apply(
                    job.id, job.user_id, extraction.operations, settings.MEMORY_EVENT_TTL_DAYS
                ):
                    return "CANCELLED"
                job.operations = [operation.model_dump() for operation in extraction.operations]
            if not job.operations:
                return "SKIPPED"
        while facts := await self.repository.facts(job.user_id, pending=True):
            for fact in facts:
                await sync_fact(memory, fact)
                await self.repository.indexed(fact)
        return "SUCCEEDED"

    def settings_out(self, account: MemoryAccount | None) -> MemorySettingsOut:
        """空账户也可显示默认开关，不能掩盖平台总开关."""
        return MemorySettingsOut(
            enabled=account.enabled if account else True,
            revision=account.revision if account else 0,
            generation=account.generation if account else 0,
            globally_enabled=settings.LONG_TERM_MEMORY_ENABLED,
        )

    async def get_settings(self, user_id: int) -> MemorySettingsOut:
        """读取用户记忆治理状态."""
        return self.settings_out(await self.repository.account(user_id))

    async def list_memories(self, user_id: int, limit: int = 100) -> list[MemoryItemOut]:
        """管理视图返回当前事实和逐字证据."""
        return [
            MemoryItemOut.model_validate(
                {**fact.model_dump(), "content": fact.content or "", "source_quote": fact.source_quote or ""}
            )
            for fact in await self.repository.facts(user_id, limit=limit)
        ]

    async def edit(self, user_id: int, fact_id: str, version: int, content: str | None) -> None:
        """直接纠错或遗忘，立即改变版本，再异步同步向量."""
        if content is not None and not allowed_text(content):
            raise ValueError("内容不属于允许记忆的范围")
        await self.repository.edit(user_id, fact_id, version, content)
        await self.dispatch(user_id)

    async def control(self, user_id: int, revision: int, enabled: bool | None = None) -> MemorySettingsOut:
        """清除和开关变更都阻止旧任务及旧缓存复活."""
        account = await self.repository.control(user_id, revision, enabled=enabled)
        await self.dispatch(user_id)
        return self.settings_out(account)

    async def list_jobs(self, user_id: int, limit: int = 20) -> list[MemoryJobOut]:
        """任务管理只暴露状态，不暴露输入聊天正文."""
        return [MemoryJobOut.model_validate(job.model_dump()) for job in await self.repository.jobs(user_id, limit)]

    async def retry_job(self, user_id: int, job_id: str) -> MemoryJobOut:
        """人工重试由认证身份授权，而非模型自动无限重试."""
        job = await self.repository.retry(user_id, job_id)
        await self.dispatch(user_id)
        return MemoryJobOut.model_validate(job.model_dump())


memory_service = MemoryService()


def get_memory_service() -> MemoryService:
    """供认证 API 注入和测试替换."""
    return memory_service
