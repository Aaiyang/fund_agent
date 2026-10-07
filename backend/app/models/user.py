"""本文件定义应用的用户模型."""

from datetime import datetime
from typing import (
    TYPE_CHECKING,
    List,
    Optional,
)

import bcrypt
from sqlmodel import (
    Field,
    Relationship,
)

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.session import Session


class User(BaseModel, table=True):
    """用户模型，保存可登录的账号.

    Attributes:
        id: 主键。
        email: 用户邮箱（唯一）。
        hashed_password: bcrypt 哈希后的密码。
        username: 可选的用户展示名。
        refresh_revoked_at: 退出登录的时刻，比它更早签发的 refresh token 一律拒绝。
        created_at: 用户创建时间。
        sessions: 与该用户聊天会话的关联关系。
    """

    id: int = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    username: Optional[str] = Field(default=None, index=False)
    refresh_revoked_at: Optional[datetime] = Field(default=None)
    sessions: List["Session"] = Relationship(back_populates="user")

    def verify_password(self, password: str) -> bool:
        """校验传入的密码与存下的哈希是否匹配."""
        return bcrypt.checkpw(password.encode("utf-8"), self.hashed_password.encode("utf-8"))

    @staticmethod
    def hash_password(password: str) -> str:
        """用 bcrypt 给密码做哈希."""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# 绕开循环 import
from app.models.session import Session  # noqa: E402
