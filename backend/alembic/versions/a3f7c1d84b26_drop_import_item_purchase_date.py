"""Drop the draft column that carried a user-chosen purchase date.

A holdings screenshot never says when a purchase settled, and the answer is not
his to guess: confirming now keeps a fund's existing date, or starts a fund seen
for the first time at the most recent session. With no input feeding it, the
column would only ever hold a date the server had already decided elsewhere.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7c1d84b26"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e2c5b0d9a317"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove holding_import_item.purchase_date."""
    op.drop_column("holding_import_item", "purchase_date")


def downgrade() -> None:
    """Bring the column back; the dates already applied stay on the positions."""
    op.add_column("holding_import_item", sa.Column("purchase_date", sa.Date(), nullable=True))
