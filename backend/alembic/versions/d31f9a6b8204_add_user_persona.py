"""Add confirmed user personas, proposals and versioned change history."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d31f9a6b8204"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a62d8b409e15"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Existing users have no inferred or prefilled profile."""
    op.create_table(
        "user_persona",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "user_persona_proposal",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.String(), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_persona_proposal_user_id", "user_persona_proposal", ["user_id"])
    op.create_table(
        "user_persona_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("proposal_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_persona_history_user_id", "user_persona_history", ["user_id"])


def downgrade() -> None:
    """Remove only application-owned persona tables."""
    op.drop_table("user_persona_history")
    op.drop_table("user_persona_proposal")
    op.drop_table("user_persona")
