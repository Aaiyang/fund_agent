"""Move the 15:00 cutoff from the holding onto the order.

The cutoff only means something to an order — it decides which session prices
it. A snapshot holding has no order behind it, so storing the cutoff there
invited the app to derive a cost from a date nobody asserted. Each BUY/SELL row
now carries the confirm day it resolved to, and the position keeps just the
earliest one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1a8f3c6b092"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c9e2b4a7d158"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the order's confirm day and drop both cutoff columns."""
    op.add_column("transaction", sa.Column("confirm_date", sa.Date(), nullable=True))
    op.execute("UPDATE \"transaction\" SET confirm_date = trade_date WHERE transaction_type IN ('BUY', 'SELL')")
    op.drop_column("portfolio_position", "purchase_after_cutoff")
    op.drop_column("holding_import_item", "purchase_after_cutoff")


def downgrade() -> None:
    """Restore the cutoff columns and drop the confirm day."""
    op.add_column(
        "portfolio_position",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "holding_import_item",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_column("transaction", "confirm_date")
