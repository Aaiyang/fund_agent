"""Background job ledger: the PostgreSQL-side record of every queued task.

Taskiq's own broker state is not authoritative here (MVP spec 7.8): the API
writes the row before enqueue and the worker updates it, so retries, failures
and timing survive a lost or restarted queue.
"""

from datetime import datetime
from uuid import uuid4

from sqlmodel import Field

from app.models.base import BaseModel
from app.utils.clock import utc_now


def _new_job_id() -> str:
    return uuid4().hex


class BackgroundJob(BaseModel, table=True):
    """One background task attempt series (fund sync, screenshot parsing, …)."""

    __tablename__ = "background_job"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=_new_job_id, primary_key=True, max_length=32)
    job_type: str = Field(max_length=40, index=True)
    status: str = Field(default="PENDING", max_length=20, index=True)
    # The business object the job acts on: a fund code or an import batch id
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
