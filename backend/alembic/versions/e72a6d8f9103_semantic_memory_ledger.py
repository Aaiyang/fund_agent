"""Add application-owned semantic memory facts and durable incremental ledger."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e72a6d8f9103"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d31f9a6b8204"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No automatic import or deletion of ungoverned legacy mem0 records."""
    op.create_table(
        "memory_account",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "memory_fact",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("source_quote", sa.String(), nullable=True),
        sa.Column("source_session_id", sa.String(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("index_state", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "key_hash", name="uq_memory_fact_user_key"),
    )
    op.create_index("ix_memory_fact_user_id", "memory_fact", ["user_id"])
    op.create_table(
        "memory_write_job",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_key", sa.String(64), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=True),
        sa.Column("operations", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "message_key", name="uq_memory_job_user_message"),
        sa.UniqueConstraint("user_id", "sequence", name="uq_memory_job_user_sequence"),
    )
    op.create_index("ix_memory_write_job_user_id", "memory_write_job", ["user_id"])
    op.create_index("ix_memory_write_job_status", "memory_write_job", ["status"])


def downgrade() -> None:
    """Remove only the three application tables; vector collection is untouched."""
    op.drop_table("memory_write_job")
    op.drop_table("memory_fact")
    op.drop_table("memory_account")
