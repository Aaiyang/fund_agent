"""Drop the per-batch 来源应用 label from holding imports.

Nothing produces it any more — the screenshot screen's text box was the only
input, and he called it out as pointless. The label that does earn its place
lives on the account (portfolio_account.source_app) and is untouched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d18e0c7f52"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a3f7c1d84b26"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove holding_import.source_app."""
    op.drop_column("holding_import", "source_app")


def downgrade() -> None:
    """Bring the column back; the batches that used it are already labelled on the account."""
    op.add_column("holding_import", sa.Column("source_app", sa.String(length=50), nullable=True))
