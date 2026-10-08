"""Protect summary writes and preserve legacy summaries before rebuilding."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a4e2176b03"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f8d3b6a2c901"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保留旧摘要；新算法从原始 checkpoint 按需重建."""
    op.add_column("session", sa.Column("context_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("session", sa.Column("context_state_legacy", sa.JSON(), nullable=True))
    op.execute('UPDATE "session" SET context_state_legacy = context_state WHERE context_state IS NOT NULL')


def downgrade() -> None:
    """恢复旧载荷后删除新增列."""
    op.execute('UPDATE "session" SET context_state = context_state_legacy WHERE context_state_legacy IS NOT NULL')
    op.drop_column("session", "context_state_legacy")
    op.drop_column("session", "context_revision")
