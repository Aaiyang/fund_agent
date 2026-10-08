"""本文件定义应用的会话模型."""

from typing import (
    TYPE_CHECKING,
    Optional,
)

from sqlmodel import (
    Field,
    JSON,
    Relationship,
)

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import User


class Session(BaseModel, table=True):
    """会话模型，保存用户的聊天会话.

    Attributes:
        id: 主键。
        user_id: 指向所属用户的外键。
        name: 会话名称，默认为空字符串。
        username: 创建会话时从用户那边复制过来的展示名。
        context_state: ContextManager 的摘要段与 Cache Epoch 状态（进程重启后恢复用）。
        created_at: 会话创建时间。
        messages: 与该会话消息的关联关系。
        user: 与该会话归属用户的关联关系。
    """

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(default="")
    username: Optional[str] = Field(default=None)
    # ContextManager 的摘要段与 Cache Epoch 状态（进程重启后恢复用）。
    # 随会话行存亡：删除会话即删除状态，不需要独立清理。
    context_state: dict | None = Field(default=None, sa_type=JSON)
    context_revision: int = Field(default=0)
    context_state_legacy: dict | None = Field(default=None, sa_type=JSON)
    user: "User" = Relationship(back_populates="sessions")
