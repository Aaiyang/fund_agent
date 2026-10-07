"""新增 fund.asset_size 与 fund.benchmark：数据源口径的基金规模与业绩比较基准."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b8c2d0f1a4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d4a7b1c9e0f3"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加上这两列基金档案字段."""
    op.add_column("fund", sa.Column("asset_size", sa.String(length=50), nullable=True))
    op.add_column("fund", sa.Column("benchmark", sa.String(length=300), nullable=True))


def downgrade() -> None:
    """删掉这两列基金档案字段."""
    op.drop_column("fund", "benchmark")
    op.drop_column("fund", "asset_size")
