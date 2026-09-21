"""Durable job wrapper: bounded retries with a PostgreSQL-side ledger (spec 7.8)."""

import asyncio

import pytest
from tenacity import wait_fixed

from app.workers import base as worker_base


class FakeLedger:
    """Records the transitions run_job asks for."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []

    async def mark_running(self, job_id: str) -> None:
        self.events.append(("RUNNING", None))

    async def finish(
        self, job_id: str, status: str, error_code: str | None = None, error_message: str | None = None
    ) -> None:
        self.events.append((status, error_code))


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> FakeLedger:
    fake = FakeLedger()
    monkeypatch.setattr(worker_base, "job_repository", fake)
    monkeypatch.setattr(worker_base.settings, "BACKGROUND_TASK_MAX_ATTEMPTS", 2)
    # Keep the retry budget under a second so the suite stays fast
    monkeypatch.setattr(worker_base, "wait_exponential", lambda **kwargs: wait_fixed(0))
    return fake


def test_success_writes_running_then_succeeded(ledger: FakeLedger) -> None:
    calls = 0

    async def work() -> None:
        nonlocal calls
        calls += 1

    assert asyncio.run(worker_base.run_job("job-1", work)) == "ok"
    assert calls == 1
    assert ledger.events == [("RUNNING", None), ("SUCCEEDED", None)]


def test_transient_failure_is_retried_within_the_budget(ledger: FakeLedger) -> None:
    attempts = 0

    async def work() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("provider hiccup")

    assert asyncio.run(worker_base.run_job("job-2", work)) == "ok"
    assert attempts == 2
    assert ledger.events[-1] == ("SUCCEEDED", None)


def test_persistent_failure_is_recorded_and_never_raises(ledger: FakeLedger) -> None:
    seen: list[str] = []

    async def work() -> None:
        raise ValueError("vision unavailable")

    async def on_failure(error: Exception) -> None:
        seen.append(str(error))

    assert asyncio.run(worker_base.run_job("job-3", work, on_failure=on_failure)) == "failed"
    assert ledger.events[-1] == ("FAILED", "ValueError")
    assert seen == ["vision unavailable"]
