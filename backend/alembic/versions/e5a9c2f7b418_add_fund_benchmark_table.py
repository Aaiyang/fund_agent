"""新增 fund_benchmark 表：存估值要用的业绩比较基准原文.

这列曾经以展示文案的身份挂在 `fund` 上并被删掉（迁移 f6c9a3d1e2b8）。现在它是
算法输入，由估值模块自己持有，界面上不读。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a9c2f7b418"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b4d18e0c7f52"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建出 fund_benchmark，一只基金一行."""
    op.create_table(
        "fund_benchmark",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("text", sa.String(length=400), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fund_benchmark_fund_code"), "fund_benchmark", ["fund_code"], unique=True)


def downgrade() -> None:
    """删掉 fund_benchmark."""
    op.drop_index(op.f("ix_fund_benchmark_fund_code"), table_name="fund_benchmark")
    op.drop_table("fund_benchmark")
