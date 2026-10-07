"""session 表加 context_state 列：摘要段与 Cache Epoch 的持久化.

此前摘要状态只存在 ContextManager 的进程内字典里，重启即丢、要重花
一次 LLM 压缩调用。文件方案试过一版，但删除会话时文件不会跟着删，
也不随用户隔离。放在会话行上：随行存亡，删除会话即删除状态。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d4e8f2a1c9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5a9c2f7b418"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 session 加可空的 context_state JSON 列."""
    op.add_column("session", sa.Column("context_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    """移除 context_state 列."""
    op.drop_column("session", "context_state")
