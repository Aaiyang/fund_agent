"""后台任务流水仓储：建任务台账行并推进它的状态."""

from app.core.database import get_async_session
from app.models.job import BackgroundJob
from app.utils.clock import utc_now


class JobRepository:
    """后台任务流水账的异步数据访问."""

    async def create(self, job_type: str, subject: str | None = None) -> BackgroundJob:
        """入队之前先把任务登记成 PENDING 状态."""
        async with get_async_session() as session:
            job = BackgroundJob(job_type=job_type, subject=subject, status="PENDING")
            session.add(job)
            await session.flush()
            return job

    async def mark_running(self, job_id: str) -> None:
        """记下本次尝试的开始时间，并把重试次数加一."""
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
        """用终态状态收尾一个任务，并带上失败详情."""
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
