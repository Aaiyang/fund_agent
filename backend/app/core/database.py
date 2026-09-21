"""Async database engine and session factory.

New fund/watchlist/portfolio modules use this asyncpg-backed engine per the
MVP spec (SQLAlchemy Async + asyncpg). The legacy chat/auth services keep
using the existing sync database_service; both point at the same PostgreSQL.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import logger


def _build_async_url() -> str:
    """Build the asyncpg connection URL from settings."""
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


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Provide a short-lived async session with commit/rollback handling.

    Yields:
        An AsyncSession. Commits on clean exit, rolls back on exception.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def async_health_check() -> bool:
    """Check async engine connectivity with a trivial query.

    Returns:
        True when the database responds, False otherwise.
    """
    from sqlalchemy import text

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("async_database_health_check_failed", error=str(e))
        return False
