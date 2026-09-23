"""In-memory lock behaviour.

The Redis path is guarded by its compare-and-delete script, which needs a live
server to exercise.
"""

import asyncio

from app.core.cache import InMemoryCacheService


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
        await cache.acquire_lock(key, ttl=0)  # already expired on the next check
        return await cache.acquire_lock(key, ttl=60)

    assert asyncio.run(scenario()) is True, "a TTL that lapsed must not block forever"
