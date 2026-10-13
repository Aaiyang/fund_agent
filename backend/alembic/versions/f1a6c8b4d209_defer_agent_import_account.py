"""Allow Agent screenshot drafts before choosing the destination account."""

from alembic import op
import sqlalchemy as sa

revision = "f1a6c8b4d209"  # pragma: allowlist secret
down_revision = "e72a6d8f9103"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep ordinary imports scoped and allow only unapplied Agent drafts without an account."""
    op.alter_column("holding_import", "account_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_holding_import_destination",
        "holding_import",
        "account_id IS NOT NULL OR (import_type = 'SCREENSHOT' AND chat_session_id IS NOT NULL "
        "AND status IN ('UPLOADED', 'PARSING', 'REVIEW_REQUIRED', 'PARSE_FAILED', 'CANCELLED'))",
    )


def downgrade() -> None:
    """Refuse to discard drafts when reverting; all drafts must first have a destination."""
    op.drop_constraint("ck_holding_import_destination", "holding_import", type_="check")
    op.alter_column("holding_import", "account_id", existing_type=sa.Integer(), nullable=False)
