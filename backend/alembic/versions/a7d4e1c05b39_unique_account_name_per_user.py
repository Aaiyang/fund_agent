"""Make account names unique per user.

The account picker shows names only, so two accounts called 支付宝 are
unreadable; the service already rejects near-duplicates and this constraint
closes the race between two concurrent creates.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a7d4e1c05b39"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f6c9a3d1e2b8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the per-user unique name constraint."""
    op.create_unique_constraint("uq_account_user_name", "portfolio_account", ["user_id", "name"])


def downgrade() -> None:
    """Drop the per-user unique name constraint."""
    op.drop_constraint("uq_account_user_name", "portfolio_account", type_="unique")
