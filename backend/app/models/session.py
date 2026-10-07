"""本文件定义应用的会话模型."""

from typing import (
    TYPE_CHECKING,
    Optional,
)

from sqlmodel import (
    Field,
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
        created_at: 会话创建时间。
        messages: 与该会话消息的关联关系。
        user: 与该会话归属用户的关联关系。
    """

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(default="")
    username: Optional[str] = Field(default=None)
    user: "User" = Relationship(back_populates="sessions")
