"""Background job repository: create and transition job ledger rows."""

from app.core.database import get_async_session
from app.models.job import BackgroundJob
from app.utils.clock import utc_now


class JobRepository:
    """Async data access for the background job ledger."""

    async def create(self, job_type: str, subject: str | None = None) -> BackgroundJob:
        """Register a job as PENDING before it is enqueued."""
        async with get_async_session() as session:
            job = BackgroundJob(job_type=job_type, subject=subject, status="PENDING")
            session.add(job)
            await session.flush()
            return job

    async def mark_running(self, job_id: str) -> None:
        """Stamp the start of an attempt and count it."""
        async with get_async_session() as session:
            job = await session.get(BackgroundJob, job_id)
            if job is None:
                return
            job.status = "RUNNING"
            job.started_at = job.started_at or utc_now()
            job.retry_count += 1
            job.updated_at = utc_now()
            session.add(job)

    async def finish(
        self, job_id: str, status: str, error_code: str | None = None, error_message: str | None = None
    ) -> None:
        """Close a job with its terminal status and any failure detail."""
        async with get_async_session() as session:
            job = await session.get(BackgroundJob, job_id)
            if job is None:
                return
            job.status = status
            job.error_code = error_code
            job.error_message = str(error_message)[:500] if error_message is not None else None
            job.finished_at = utc_now()
            job.updated_at = utc_now()
            session.add(job)


job_repository = JobRepository()
