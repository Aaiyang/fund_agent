"""按用户隔离的模型档案与当前选择."""

from datetime import datetime

from sqlmodel import Field, JSON

from app.models.base import BaseModel
from app.utils.clock import utc_now


class UserLlmSettings(BaseModel, table=True):
    """用户个人供应商配置；JSON 内的密钥仅存密文."""

    __tablename__ = "user_llm_settings"  # pyright: ignore[reportAssignmentType]

    user_id: int = Field(primary_key=True, foreign_key="user.id", ondelete="CASCADE")
    profiles: list[dict[str, str]] = Field(default_factory=list, sa_type=JSON)
    active: str = Field(default="默认 GLM Flash")
    updated_at: datetime = Field(default_factory=utc_now)
