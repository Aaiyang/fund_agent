"""后台任务流水账：每个入队任务在 PostgreSQL 一侧的台账.

Taskiq 自己 broker 里的状态不作数（MVP spec 7.8）：API 在入队之前先把这行写好，
之后由 worker 更新它，所以任务队列丢失或重启之后，重试次数、失败信息和耗时依然查得到。
"""

from datetime import datetime
from uuid import uuid4

from sqlmodel import Field

from app.models.base import BaseModel
from app.utils.clock import utc_now


def _new_job_id() -> str:
    return uuid4().hex


class BackgroundJob(BaseModel, table=True):
    """一个后台任务的多次尝试记录（基金同步、截图解析……）."""

    __tablename__ = "background_job"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=_new_job_id, primary_key=True, max_length=32)
    job_type: str = Field(max_length=40, index=True)
    status: str = Field(default="PENDING", max_length=20, index=True)
    # 任务作用的业务对象：一个基金代码，或一个导入批次的 id
    subject: str | None = Field(default=None, max_length=64, index=True)

    retry_count: int = Field(default=0)
    error_code: str | None = Field(default=None, max_length=60)
    error_message: str | None = Field(default=None, max_length=500)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )
