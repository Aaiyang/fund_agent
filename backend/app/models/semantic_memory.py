"""长期记忆的用户控制、单条事实与持久化增量工作账本."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, JSON

from app.models.base import BaseModel
from app.utils.clock import utc_now


class MemoryAccount(BaseModel, table=True):
    """短事务内锁定用户控制行，序号与代际永远单调递增."""

    __tablename__ = "memory_account"  # pyright: ignore[reportAssignmentType]
    user_id: int = Field(primary_key=True, foreign_key="user.id", ondelete="CASCADE")
    enabled: bool = True
    generation: int = 0
    revision: int = 0
    sequence: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryFact(BaseModel, table=True):
    """原文事实的当前版本；删除后只保留不可读键哈希和同步状态."""

    __tablename__ = "memory_fact"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("user_id", "key_hash", name="uq_memory_fact_user_key"),)
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    key_hash: str = Field(max_length=64)
    kind: str
    content: str | None = None
    source_quote: str | None = None
    source_session_id: str = ""
    source_message_id: str = ""
    source_sequence: int = 0
    generation: int = 0
    version: int = 1
    status: str = "ACTIVE"
    index_state: str = "PENDING"
    expires_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryWriteJob(BaseModel, table=True):
    """一条实际新增用户消息对应一个任务；唯一键也是逐消息写入水位."""

    __tablename__ = "memory_write_job"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "message_key", name="uq_memory_job_user_message"),
        UniqueConstraint("user_id", "sequence", name="uq_memory_job_user_sequence"),
    )
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    message_key: str = Field(max_length=64)
    source_session_id: str = ""
    source_message_id: str = ""
    sequence: int
    generation: int
    kind: str = "EXTRACT"
    text: str | None = None
    operations: list[dict] | None = Field(default=None, sa_type=JSON)
    status: str = Field(default="PENDING", index=True)
    attempts: int = 0
    error_code: str | None = None
    lease_until: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
