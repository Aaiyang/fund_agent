"""异步数据库引擎与会话工厂.

按 MVP spec，基金、资产组合、聊天与认证统一使用 SQLAlchemy Async + asyncpg 引擎。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import logger


def _build_async_url() -> str:
    """用配置项拼出 asyncpg 的连接 URL."""
    return (
        "postgresql+asyncpg://"
        f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )


async_engine: AsyncEngine = create_async_engine(
    _build_async_url(),
    pool_pre_ping=True,
    pool_size=settings.POSTGRES_POOL_SIZE,
    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
    pool_timeout=30,
    pool_recycle=1800,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

_TRANSACTION_SESSION: ContextVar[AsyncSession | None] = ContextVar("transaction_session", default=None)


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """提供短生命周期的异步会话，并负责提交/回滚.

    Yields:
        一个 AsyncSession。正常退出时提交，抛异常时回滚。
    """
    scoped = _TRANSACTION_SESSION.get()
    if scoped is not None:
        yield scoped
        return
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def transaction_scope() -> AsyncIterator[AsyncSession]:
    """让串行仓储调用共用同一事务；作用域内不得并发使用数据库会话."""
    async with get_async_session() as session:
        token = _TRANSACTION_SESSION.set(session)
        try:
            yield session
        finally:
            _TRANSACTION_SESSION.reset(token)


async def async_health_check() -> bool:
    """用最简单的查询探测异步引擎的连通性.

    Returns:
        数据库有响应返回 True，否则 False。
    """
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("async_database_health_check_failed", error=str(e))
        return False
