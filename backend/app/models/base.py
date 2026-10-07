"""全部 ORM 模型的基类与公共 import."""

from datetime import datetime
from sqlmodel import Field, SQLModel
from app.utils.clock import utc_now


class BaseModel(SQLModel):
    """各模型共用的基类，只带公共字段.

    SQLModel 用类名小写后的结果推导 ``__tablename__``，所以每个多词类名的模型都
    必须显式声明 ``__tablename__``，才能对上 Alembic 迁移建出的 snake_case 表。
    """

    created_at: datetime = Field(default_factory=utc_now)
