"""Let the review page carry a purchase date.

A holdings screenshot never shows when a fund was bought, so confirming an
import used to stamp every new position with the import day. That date then
drove the cost estimate, which made a number the system invented look like a
fact. The draft row now holds the date itself, prefilled and correctable, so
only what the user saw on the review page reaches portfolio_position.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e2b4a7d158"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b3f1d2a6c470"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the confirmation date and its cutoff side to a pending import row."""
    op.add_column("holding_import_item", sa.Column("purchase_date", sa.Date(), nullable=True))
    op.add_column(
        "holding_import_item",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Drop both columns."""
    op.drop_column("holding_import_item", "purchase_after_cutoff")
    op.drop_column("holding_import_item", "purchase_date")
