"""Base models and common imports for all models."""

from datetime import datetime
from sqlmodel import Field, SQLModel
from app.utils.clock import utc_now


class BaseModel(SQLModel):
    """Base model with common fields.

    SQLModel derives ``__tablename__`` from the lowercased class name, so every
    multi-word model must declare ``__tablename__`` explicitly to match the
    snake_case tables created by the Alembic migrations.
    """

    created_at: datetime = Field(default_factory=utc_now)
