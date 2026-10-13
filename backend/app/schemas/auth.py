"""应用的鉴权相关 schema 定义."""

import re
from datetime import datetime

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from app.schemas.base import BaseResponse


class Token(BaseModel):
    """鉴权 token 模型.

    Attributes:
        access_token: 签发的 JWT access token。
        token_type: token 类型（恒为 "bearer"）。
        expires_at: token 的过期时间戳。
    """

    access_token: str = Field(..., description="The JWT access token")
    token_type: str = Field(default="bearer", description="The type of token")
    expires_at: datetime = Field(..., description="The token expiration timestamp")


class TokenResponse(BaseResponse):
    """登录端点的响应模型.

    Attributes:
        access_token: 本次登录签发的 JWT access token
        token_type: token 类型（恒为 "bearer"）
        expires_at: token 的过期时刻
        refresh_token: 可选的长效 refresh token（spec 3.1）
    """

    access_token: str = Field(..., description="The JWT access token")
    token_type: str = Field(default="bearer", description="The type of token")
    expires_at: datetime = Field(..., description="When the token expires")
    refresh_token: str | None = Field(default=None, description="The JWT refresh token, when issued")


class UserCreate(BaseModel):
    """用户注册的请求模型.

    Attributes:
        email: 用户邮箱
        password: 用户密码
        username: 可选的显示名
    """

    email: EmailStr = Field(..., description="User's email address")
    password: SecretStr = Field(..., description="User's password", min_length=8, max_length=64)
    username: str | None = Field(default=None, description="Optional display name", max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        """校验密码强度.

        Args:
            v: 待校验的密码

        Returns:
            SecretStr: 校验通过的密码

        Raises:
            ValueError: 密码强度不达标时抛出
        """
        password = v.get_secret_value()

        # 逐条检查常规密码强度要求
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"[0-9]", password):
            raise ValueError("Password must contain at least one number")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("Password must contain at least one special character")

        return v


class UserProfileUpdateRequest(BaseModel):
    """PATCH /auth/me 的请求模型；省略的字段保持原值.

    Attributes:
        email: 新邮箱，None 表示不改
        username: 新显示名；空字符串表示清空
    """

    email: EmailStr | None = Field(default=None, description="New email address")
    username: str | None = Field(default=None, description="New display name", max_length=50)


class UserResponse(BaseResponse):
    """用户相关操作的响应模型.

    Attributes:
        id: 用户 ID
        email: 用户邮箱
        username: 可选的显示名
        token: 鉴权 token
    """

    id: int = Field(..., description="User's ID")
    email: str = Field(..., description="User's email address")
    username: str | None = Field(default=None, description="Optional display name")
    token: Token = Field(..., description="Authentication token")


class CurrentUserResponse(BaseResponse):
    """GET /auth/me 的响应模型（spec 3.1 获取当前用户信息）.

    Attributes:
        id: 用户 ID
        email: 用户邮箱
        username: 可选的显示名
        created_at: 账号创建时间
    """

    id: int = Field(..., description="User's ID")
    email: str = Field(..., description="User's email address")
    username: str | None = Field(default=None, description="Optional display name")
    created_at: datetime | None = Field(default=None, description="When the account was created")


class SessionResponse(BaseResponse):
    """创建会话的响应模型.

    Attributes:
        session_id: 聊天会话的唯一标识
        name: 会话名称（默认为空字符串）
        token: 该会话的鉴权 token
        created_at: 会话创建时间（naive UTC）；列表按它倒序排，客户端拿它标时间
    """

    session_id: str = Field(..., description="The unique identifier for the chat session")
    name: str = Field(default="", description="Name of the session", max_length=100)
    token: Token = Field(..., description="The authentication token for the session")
    created_at: datetime = Field(..., description="When this session was created")

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        """清洗会话名称.

        Args:
            v: 待清洗的名称

        Returns:
            str: 清洗后的名称
        """
        # 去掉可能有风险的字符
        sanitized = re.sub(r'[<>{}[\]()\'"`]', "", v)
        return sanitized
