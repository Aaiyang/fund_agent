"""内存实现的锁行为.

Redis 那条路径由 compare-and-delete 脚本保证原子性，得连上真实服务器才跑得动，
这里覆盖不到。
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
        await cache.acquire_lock(key, ttl=0)  # ttl 为 0，下一次检查时锁已经过期
        return await cache.acquire_lock(key, ttl=60)

    assert asyncio.run(scenario()) is True, "a TTL that lapsed must not block forever"
