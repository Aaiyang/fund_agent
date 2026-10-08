"""Alembic 迁移环境配置.

数据库连接串取自应用自身的 settings，保证迁移版本和正在运行的应用配置始终一致。
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context
from app.core.config import settings
from app.models.fund import Fund, FundNav  # noqa: F401
from app.models.holding_import import HoldingImport, HoldingImportItem  # noqa: F401
from app.models.job import BackgroundJob  # noqa: F401
from app.models.market import IndexQuote  # noqa: F401
from app.models.portfolio import PortfolioAccount, PortfolioPosition, Transaction  # noqa: F401
from app.models.session import Session  # noqa: F401
from app.models.thread import Thread  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.user_llm_settings import UserLlmSettings  # noqa: F401
from app.models.user_persona import UserPersona, UserPersonaHistory, UserPersonaProposal  # noqa: F401
from app.models.watchlist import Watchlist, WatchlistGroup, WatchlistGroupItem  # noqa: F401

# Alembic 的 Config 对象
config = context.config

# 按 ini 文件初始化 Python 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用应用 settings 拼出数据库连接串
DATABASE_URL = (
    f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 把 Alembic 指向 SQLModel 的 metadata，autogenerate 才能比对表结构
target_metadata = SQLModel.metadata

# 由外部系统维护的表（LangGraph checkpoint、mem0、pgvector）
# Alembic 永远不要改动它们
EXCLUDE_TABLES = {
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "checkpoints",
    "longterm_memory",
    "mem0migrations",
}


def include_object(object, name, type_, reflected, compare_to):
    """过滤掉由外部系统维护的表，不让它们进入比对."""
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """以 'offline' 模式执行迁移.

    只把 SQL 语句输出到 stdout，不连数据库执行。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以 'online' 模式执行迁移.

    创建引擎，直接在真实数据库上跑迁移。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
