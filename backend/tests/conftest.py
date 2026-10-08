"""测试配置：在导入任何 app 模块之前把环境变量默认值设好，并集中放置共享 fixture."""

import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-0123456789abcdef-0123456789ab")
os.environ.setdefault("VALKEY_HOST", "")
os.environ.setdefault("TASKIQ_REDIS_URL", "")
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
os.environ.setdefault("LONG_TERM_MEMORY_ENABLED", "false")
os.environ.setdefault("SESSION_NAMING_ENABLED", "false")


@pytest.fixture(autouse=True)
def _fake_context_state_store(monkeypatch):
    """内存版摘要状态仓库：测试永不触库，序列化/解析走真实实现.

    测试需要直接断言仓库内容时，按名注入 ``_fake_context_state_store``。
    """
    from app.agent.context import state_store

    store: dict[str, dict] = {}

    async def fake_load(thread_key: str):
        payload = store.get(thread_key)
        parsed = state_store.parse_state(payload) if payload else None
        segments, sequence = parsed if parsed else ([], 1)
        return state_store.ContextStateRead(
            segments=segments, epoch_sequence=sequence, revision=(payload or {}).get("_revision", 0)
        )

    async def fake_save(thread_key: str, segments, epoch_sequence: int, *, expected_revision: int) -> bool:
        revision = store.get(thread_key, {}).get("_revision", 0)
        if revision != expected_revision:
            return False
        store[thread_key] = {**state_store.serialize_state(segments, epoch_sequence), "_revision": revision + 1}
        return True

    monkeypatch.setattr(state_store, "load_context_state", fake_load)
    monkeypatch.setattr(state_store, "save_context_state", fake_save)
    return store
