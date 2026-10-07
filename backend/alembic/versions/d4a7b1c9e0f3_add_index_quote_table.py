"""新增 index_quote 表：为基金详情页的对比线存基准指数收盘点位."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7b1c9e0f3"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b8e3f1a6c405"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建出 index_quote，带上查询索引与按日唯一约束."""
    op.create_table(
        "index_quote",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("index_code", sa.String(length=12), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("index_code", "trade_date", name="uq_index_quote_code_date"),
    )
    op.create_index(op.f("ix_index_quote_index_code"), "index_quote", ["index_code"])
    op.create_index(op.f("ix_index_quote_trade_date"), "index_quote", ["trade_date"])


def downgrade() -> None:
    """删掉 index_quote."""
    op.drop_index(op.f("ix_index_quote_trade_date"), table_name="index_quote")
    op.drop_index(op.f("ix_index_quote_index_code"), table_name="index_quote")
    op.drop_table("index_quote")
