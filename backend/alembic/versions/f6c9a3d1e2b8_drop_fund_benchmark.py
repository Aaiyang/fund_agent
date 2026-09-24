"""Drop fund.benchmark: the stated benchmark is no longer shown or served.

The index comparison line on the fund detail page reads /indexes instead, so
the verbatim 业绩比较基准 snapshot had no consumer left.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6c9a3d1e2b8"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5b8c2d0f1a4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the profile benchmark column."""
    op.drop_column("fund", "benchmark")


def downgrade() -> None:
    """Re-add the profile benchmark column; previously synced text is lost."""
    op.add_column("fund", sa.Column("benchmark", sa.String(length=300), nullable=True))
