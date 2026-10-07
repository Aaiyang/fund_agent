"""本文件定义应用的会话线程模型."""

from datetime import (
    datetime,
)

from sqlmodel import (
    Field,
    SQLModel,
)
from app.utils.clock import utc_now


class Thread(SQLModel, table=True):
    """会话线程模型，保存一个个对话线程.

    Attributes:
        id: 主键。
        created_at: 线程创建时间。
        messages: 该线程内消息的关联关系。
    """

    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
