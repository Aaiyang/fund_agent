"""内存实现的锁行为.

Redis 那条路径由 compare-and-delete 脚本保证原子性，得连上真实服务器才跑得动，
这里覆盖不到。
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.cache import InMemoryCacheService, ValkeyCacheService


@pytest.mark.asyncio
async def test_valkey_release_passes_owner_token_to_compare_and_delete() -> None:
    cache = ValkeyCacheService()
    client = AsyncMock()
    cache._client = client
    cache._lock_tokens["lock:test"] = "owner-token"

    await cache.release_lock("lock:test")

    client.eval.assert_awaited_once()
    assert client.eval.call_args.args[1:] == (1, "lock:test", "owner-token")
    assert "lock:test" not in cache._lock_tokens


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
        await cache.release_lock(key)
        third = await cache.acquire_lock(key, ttl=60)
        return first, second, third

    first, second, third = asyncio.run(scenario())
    assert first is True
    assert second is False, "a live lock must refuse the second acquirer"
    assert third is True, "releasing must free the lock"


def test_expired_lock_is_reclaimable() -> None:
    async def scenario() -> bool:
        cache = InMemoryCacheService()
        key = "sync:fund:012414"
        await cache.acquire_lock(key, ttl=0)  # ttl 为 0，下一次检查时锁已经过期
        return await cache.acquire_lock(key, ttl=60)

    assert asyncio.run(scenario()) is True, "a TTL that lapsed must not block forever"
