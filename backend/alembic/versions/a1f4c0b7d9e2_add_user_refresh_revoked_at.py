"""Add user.refresh_revoked_at for refresh token revocation on logout.

Revision ID: a1f4c0b7d9e2
Revises: c7d2e91a4b08
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1f4c0b7d9e2"  # pragma: allowlist secret
down_revision = "c7d2e91a4b08"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Stamp users with a refresh token revocation time."""
    op.add_column("user", sa.Column("refresh_revoked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop the revocation stamp."""
    op.drop_column("user", "refresh_revoked_at")
