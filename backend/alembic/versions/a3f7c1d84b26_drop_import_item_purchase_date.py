"""删掉草稿行里那列由用户自选的购买日期.

持仓截图不会写申购是哪一天成交的，这个答案也不该让用户猜：现在确认时沿用该基金
已有的日期，首次出现的基金则取最近一个交易时段。既然没有任何输入喂给这列，它只会
存下服务端在别处早已定好的日期。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7c1d84b26"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e2c5b0d9a317"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 holding_import_item.purchase_date."""
    op.drop_column("holding_import_item", "purchase_date")


def downgrade() -> None:
    """把列加回来；已经落到持仓上的日期仍留在持仓里."""
    op.add_column("holding_import_item", sa.Column("purchase_date", sa.Date(), nullable=True))
