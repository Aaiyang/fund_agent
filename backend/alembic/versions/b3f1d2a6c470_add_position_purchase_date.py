"""记下申购被确认在哪一天.

持有天数原先没有真实来源：它从最早的一条流水开始算，而那是持仓被导入的那天，不
是真正买入的那天。基金下单落在截止点 15:00 之前按当日净值成交，之后按下一个交易时
段成交，所以下面这两列记的才是用户真正知道的东西——一个日期，以及它落在截止点的哪
一侧。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1d2a6c470"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a7d4e1c05b39"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加上确认日，以及它落在截止点哪一侧的标记."""
    op.add_column("portfolio_position", sa.Column("purchase_date", sa.Date(), nullable=True))
    op.add_column(
        "portfolio_position",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """删掉这两列."""
    op.drop_column("portfolio_position", "purchase_after_cutoff")
    op.drop_column("portfolio_position", "purchase_date")
