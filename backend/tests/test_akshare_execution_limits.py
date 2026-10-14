"""真实 executor 线程在协程超时或取消后仍占有并发许可."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from app.integrations.fund_data import akshare_provider as module
from app.integrations.fund_data.akshare_provider import AKShareFundProvider


@pytest.mark.parametrize("cancel", [False, True])
async def test_timed_out_or_cancelled_thread_retains_permit_until_completion(monkeypatch, cancel):
    provider = AKShareFundProvider()
    provider._semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(module, "AKSHARE_AVAILABLE", True)
    monkeypatch.setattr(module, "ak", object())
    monkeypatch.setattr(module.settings, "AKSHARE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(provider, "_throttle", AsyncMock())
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    starts = []

    def blocked(*args, **kwargs):
        starts.append(1)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(3):
            raise RuntimeError("fixture thread was not released")
        return []

    monkeypatch.setattr(provider, "_call_sync", blocked)
    first = asyncio.create_task(provider._call.__wrapped__(provider, "fixture"))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            with pytest.raises(TimeoutError):
                await first
        assert provider._semaphore.locked()
        second = asyncio.create_task(provider._call.__wrapped__(provider, "fixture"))
        await asyncio.sleep(0.02)
        assert len(starts) == 1 and not second.done()
    finally:
        release.set()
        if second is not None:
            await asyncio.wait_for(second, 1)
        if not first.done():
            await first
    await asyncio.sleep(0)
    assert not provider._semaphore.locked()


async def test_cancel_during_throttle_returns_unused_permit(monkeypatch):
    provider = AKShareFundProvider()
    provider._semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(module, "AKSHARE_AVAILABLE", True)
    monkeypatch.setattr(module, "ak", object())
    entered = asyncio.Event()

    async def throttle():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(provider, "_throttle", throttle)
    task = asyncio.create_task(provider._call.__wrapped__(provider, "fixture"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not provider._semaphore.locked()
