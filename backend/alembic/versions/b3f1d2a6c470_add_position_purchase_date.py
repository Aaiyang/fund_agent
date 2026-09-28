"""Record when a purchase was confirmed.

持有天数 had no real source: it counted from the earliest transaction row, which
is the day the holding was *imported*, not the day it was bought. Funds price an
order at the same day's NAV before 15:00 and the next session's after, so the
pair below captures what the user actually knows — a date and which side of the
cutoff it fell on.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1d2a6c470"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a7d4e1c05b39"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the confirmation date and its cutoff side."""
    op.add_column("portfolio_position", sa.Column("purchase_date", sa.Date(), nullable=True))
    op.add_column(
        "portfolio_position",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Drop both columns."""
    op.drop_column("portfolio_position", "purchase_after_cutoff")
    op.drop_column("portfolio_position", "purchase_date")
