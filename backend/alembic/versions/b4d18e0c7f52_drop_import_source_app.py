"""删掉持仓导入中按批次记录的 来源应用 标签.

已经没有任何入口会写它了——截图导入页的文本框是唯一的输入，而用户明确指出这一项没
有意义。真正起作用的那份标签记在账户上（portfolio_account.source_app），保持不动。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d18e0c7f52"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a3f7c1d84b26"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 holding_import.source_app."""
    op.drop_column("holding_import", "source_app")


def downgrade() -> None:
    """把列加回来；用过这一标签的批次已经把值记在账户上了."""
    op.add_column("holding_import", sa.Column("source_app", sa.String(length=50), nullable=True))
