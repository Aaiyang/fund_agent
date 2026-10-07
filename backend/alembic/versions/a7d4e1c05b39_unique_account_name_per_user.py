"""让账户名在同一用户下唯一.

账户选择器只显示名字，两个都叫 支付宝 的账户根本分不清；服务层已经在拒绝近似重复
的名字，这条约束补上了两个并发创建之间的竞态。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a7d4e1c05b39"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f6c9a3d1e2b8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加上同一用户下账户名唯一的约束."""
    op.create_unique_constraint("uq_account_user_name", "portfolio_account", ["user_id", "name"])


def downgrade() -> None:
    """删掉同一用户下账户名唯一的约束."""
    op.drop_constraint("uq_account_user_name", "portfolio_account", type_="unique")
