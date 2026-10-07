"""给 user 表加 refresh_revoked_at，退出登录时用它吊销已签发的 refresh token.

Revision ID: a1f4c0b7d9e2
Revises: c7d2e91a4b08
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

# 迁移版本号标识，Alembic 靠它串起迁移链
revision = "a1f4c0b7d9e2"  # pragma: allowlist secret
down_revision = "c7d2e91a4b08"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给 user 表加上 refresh token 吊销时刻这一列."""
    op.add_column("user", sa.Column("refresh_revoked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """删掉这列吊销时刻."""
    op.drop_column("user", "refresh_revoked_at")
