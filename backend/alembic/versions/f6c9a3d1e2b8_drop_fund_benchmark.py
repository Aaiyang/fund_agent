"""删掉 fund.benchmark：这份业绩比较基准已经不再展示也不再下发.

基金详情页的指数对比线改读 /indexes，那份照抄上游的 业绩比较基准 快照已经没有消费方。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6c9a3d1e2b8"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5b8c2d0f1a4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删掉档案里的业绩比较基准列."""
    op.drop_column("fund", "benchmark")


def downgrade() -> None:
    """把业绩比较基准列加回来；此前同步过的文本已经找不回了."""
    op.add_column("fund", sa.Column("benchmark", sa.String(length=300), nullable=True))
