"""Add the standing 定投 plan table.

A plan is something the user states — 每几周/每月几号、多少钱 — so the app can
work out which installments it was told to record and write them as ordinary
purchases instead of asking him to tap 同步定投 every time.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2c5b0d9a317"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d1a8f3c6b092"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create auto_invest_plan."""
    op.create_table(
        "auto_invest_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False, server_default="weekly"),
        sa.Column("run_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["portfolio_account.id"]),
    )
    op.create_index("ix_auto_invest_plan_user_id", "auto_invest_plan", ["user_id"])
    op.create_index("ix_auto_invest_plan_account_id", "auto_invest_plan", ["account_id"])
    op.create_index("ix_auto_invest_plan_fund_code", "auto_invest_plan", ["fund_code"])


def downgrade() -> None:
    """Drop the table."""
    op.drop_index("ix_auto_invest_plan_fund_code", table_name="auto_invest_plan")
    op.drop_index("ix_auto_invest_plan_account_id", table_name="auto_invest_plan")
    op.drop_index("ix_auto_invest_plan_user_id", table_name="auto_invest_plan")
    op.drop_table("auto_invest_plan")
