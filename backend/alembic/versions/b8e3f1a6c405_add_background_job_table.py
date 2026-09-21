"""Add the background_job ledger table.

Revision ID: b8e3f1a6c405
Revises: a1f4c0b7d9e2
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8e3f1a6c405"  # pragma: allowlist secret
down_revision = "a1f4c0b7d9e2"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the durable background task ledger (spec 7.8)."""
    op.create_table(
        "background_job",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_job")),
    )
    op.create_index(op.f("ix_background_job_job_type"), "background_job", ["job_type"])
    op.create_index(op.f("ix_background_job_status"), "background_job", ["status"])
    op.create_index(op.f("ix_background_job_subject"), "background_job", ["subject"])


def downgrade() -> None:
    """Drop the ledger table."""
    op.drop_index(op.f("ix_background_job_subject"), table_name="background_job")
    op.drop_index(op.f("ix_background_job_status"), table_name="background_job")
    op.drop_index(op.f("ix_background_job_job_type"), table_name="background_job")
    op.drop_table("background_job")
