"""数据库画像是已确认字段的唯一来源，候选与变更历史独立保存."""

from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, JSON

from app.models.base import BaseModel
from app.utils.clock import utc_now


class UserPersona(BaseModel, table=True):
    """每用户一条画像；清除后保留空记录及单调递增版本."""

    __tablename__ = "user_persona"  # pyright: ignore[reportAssignmentType]

    user_id: int = Field(primary_key=True, foreign_key="user.id", ondelete="CASCADE")
    revision: int = Field(default=0)
    data: dict = Field(default_factory=dict, sa_type=JSON)
    provenance: dict = Field(default_factory=dict, sa_type=JSON)
    updated_at: datetime = Field(default_factory=utc_now)


class UserPersonaProposal(BaseModel, table=True):
    """模型只能创建候选，不能写已确认画像."""

    __tablename__ = "user_persona_proposal"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    base_revision: int
    changes: dict = Field(sa_type=JSON)
    evidence: str
    source_session_id: str
    source_message_id: str
    status: str = Field(default="PENDING")
    updated_at: datetime = Field(default_factory=utc_now)


class UserPersonaHistory(BaseModel, table=True):
    """已确认更新的来源和版本，随用户或画像清除而删除."""

    __tablename__ = "user_persona_history"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    revision: int
    changes: dict = Field(sa_type=JSON)
    source: str
    proposal_id: str | None = None
