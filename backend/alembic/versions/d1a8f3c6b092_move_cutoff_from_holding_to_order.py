"""把截止点 15:00 从持仓挪到订单上.

截止点只对订单有意义——它决定这笔订单按哪个交易时段成交。快照式持仓背后并没有订单，
把截止点存在那儿，等于放任应用拿一个谁也没声明过的日期去推算成本。现在每条 BUY/SELL
流水都带上它最终落到的确认日，持仓只保留其中最早的那个。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1a8f3c6b092"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c9e2b4a7d158"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给流水加上确认日，并删掉两处表示截止点的列."""
    op.add_column("transaction", sa.Column("confirm_date", sa.Date(), nullable=True))
    op.execute("UPDATE \"transaction\" SET confirm_date = trade_date WHERE transaction_type IN ('BUY', 'SELL')")
    op.drop_column("portfolio_position", "purchase_after_cutoff")
    op.drop_column("holding_import_item", "purchase_after_cutoff")


def downgrade() -> None:
    """把两处截止点列加回来，并删掉确认日."""
    op.add_column(
        "portfolio_position",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "holding_import_item",
        sa.Column("purchase_after_cutoff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_column("transaction", "confirm_date")
