"""Add isolated user LLM settings with encrypted credentials."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8d3b6a2c901"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b7d4e8f2a1c9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建用户个人模型设置表，用户删除时级联清理."""
    op.create_table(
        "user_llm_settings",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column("active", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """删除个人模型设置表."""
    op.drop_table("user_llm_settings")
