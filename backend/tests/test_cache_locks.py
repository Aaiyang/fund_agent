"""内存实现的锁行为.

Redis 那条路径由 compare-and-delete 脚本保证原子性，得连上真实服务器才跑得动，
这里覆盖不到。
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.cache import InMemoryCacheService, ValkeyCacheService, LockLease


@pytest.mark.asyncio
async def test_valkey_release_passes_owner_token_to_compare_and_delete() -> None:
    cache = ValkeyCacheService()
    client = AsyncMock()
    cache._client = client
    await cache.release_lock(LockLease("lock:test", "owner-token"))

    client.eval.assert_awaited_once()
    assert client.eval.call_args.args[1:] == (1, "lock:test", "owner-token")


async def test_sensitive_lock_fails_closed_when_valkey_is_unavailable() -> None:
    cache = ValkeyCacheService()
    assert not await cache.acquire_lock("holding:review", fail_open=False)
    assert await cache.acquire_lock("fund:sync")
    cache._client = AsyncMock()
    cache._client.set.side_effect = ConnectionError("fixture unavailable")
    assert not await cache.acquire_lock("holding:review", fail_open=False)


def test_lock_excludes_a_second_acquirer_until_released() -> None:
    async def scenario() -> tuple[bool, bool, bool]:
        cache = InMemoryCacheService()
        key = "sync:fund:011452"
        first = await cache.acquire_lock(key, ttl=60)
        second = await cache.acquire_lock(key, ttl=60)
        assert first is not None
        await cache.release_lock(first)
        third = await cache.acquire_lock(key, ttl=60)
        return bool(first), bool(second), bool(third)

    first, second, third = asyncio.run(scenario())
    assert first is True
    assert second is False, "a live lock must refuse the second acquirer"
    assert third is True, "releasing must free the lock"


def test_expired_lock_is_reclaimable() -> None:
    async def scenario() -> bool:
        cache = InMemoryCacheService()
        key = "sync:fund:012414"
        await cache.acquire_lock(key, ttl=0)  # ttl 为 0，下一次检查时锁已经过期
        return bool(await cache.acquire_lock(key, ttl=60))

    assert asyncio.run(scenario()) is True, "a TTL that lapsed must not block forever"


async def test_old_owner_cannot_release_reclaimed_in_memory_lock() -> None:
    cache = InMemoryCacheService()
    old = await cache.acquire_lock("lock:test", ttl=0)
    current = await cache.acquire_lock("lock:test")
    assert old is not None and current is not None
    await cache.release_lock(old)
    assert await cache.acquire_lock("lock:test") is None
    await cache.release_lock(current)
    assert await cache.acquire_lock("lock:test") is not None


async def test_old_owner_cannot_release_reclaimed_redis_lock() -> None:
    cache = ValkeyCacheService()
    values: dict[str, str] = {}
    client = AsyncMock()

    async def acquire(key, token, **kwargs):
        if key in values:
            return False
        values[key] = token
        return True

    async def release(script, count, key, token):
        if values.get(key) == token:
            del values[key]
            return 1
        return 0

    client.set.side_effect = acquire
    client.eval.side_effect = release
    cache._client = client
    old = await cache.acquire_lock("lock:test")
    values.clear()
    current = await cache.acquire_lock("lock:test")
    assert old is not None and current is not None
    await cache.release_lock(old)
    assert values["lock:test"] == current.token
    await cache.release_lock(current)
    assert values == {}
