"""让确认页可以带上申购日期.

持仓截图不会显示基金是什么时候买的，所以以前确认导入时，会给每个新建的持仓盖上导入
那天的日期；这个日期又参与成本估算，等于把系统编出来的数当成事实。现在草稿行自己存
这个日期，预填且可改，因此只有用户在确认页上看到的内容才会进入 portfolio_position。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e2b4a7d158"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b3f1d2a6c470"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给待确认的导入行加上确认日，以及它落在截止点哪一侧的标记."""
    op.add_column("holding_import_item", sa.Column("purchase_date", sa.Date(), nullable=True))
    op.add_column(
        "holding_import_item",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """删掉这两列."""
    op.drop_column("holding_import_item", "purchase_after_cutoff")
    op.drop_column("holding_import_item", "purchase_date")
