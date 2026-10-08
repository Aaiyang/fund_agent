"""Bind Agent screenshot imports to their authenticated chat session."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a62d8b409e15"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c9a4e2176b03"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Existing imports retain their original non-chat behavior."""
    op.add_column("holding_import", sa.Column("chat_session_id", sa.String(), nullable=True))
    op.create_index("ix_holding_import_chat_session_id", "holding_import", ["chat_session_id"])


def downgrade() -> None:
    """Remove the chat binding after applications stop using it."""
    op.drop_index("ix_holding_import_chat_session_id", table_name="holding_import")
    op.drop_column("holding_import", "chat_session_id")
