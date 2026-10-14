"""This file contains the database service for the application."""

from typing import (
    List,
    Optional,
)

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import (
    col,
    delete,
    select,
)

from app.core.database import async_engine, async_session_factory, get_async_session
from app.core.logging import logger
from app.core.metrics import component_up
from app.agent.context import state_store
from app.agent.context.manager import context_manager
from app.models.holding_import import HoldingImport, HoldingImportItem
from app.models.portfolio import (
    AutoInvestPlan,
    PortfolioAccount,
    PortfolioPosition,
    Transaction as PortfolioTransaction,
)
from app.models.session import Session as ChatSession
from app.models.user import User
from app.models.watchlist import (
    Watchlist,
    WatchlistGroup,
    WatchlistGroupItem,
)
from app.utils.clock import utc_now


class DatabaseService:
    """Service class for database operations.

    This class handles all database operations for Users, Sessions, and Messages.
    It uses SQLModel with the shared SQLAlchemy async engine.
    """

    def __init__(self) -> None:
        """复用领域仓储的异步引擎，不再创建第二个同步连接池."""
        self.engine = async_engine

    async def create_user(self, email: str, password: str, username: str | None = None) -> User:
        """Create a new user.

        Args:
            email: User's email address
            password: Hashed password
            username: Optional display name

        Returns:
            User: The created user
        """
        async with get_async_session() as session:
            user = User(email=email, hashed_password=password, username=username)
            session.add(user)
            await session.flush()
            await session.refresh(user)
            logger.info("user_created", email=email)
            return user

    async def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by ID.

        Args:
            user_id: The ID of the user to retrieve

        Returns:
            Optional[User]: The user if found, None otherwise
        """
        async with get_async_session() as session:
            user = await session.get(User, user_id)
            return user

    async def update_user(
        self, user_id: int, email: Optional[str] = None, username: Optional[str] = None
    ) -> Optional[User]:
        """Apply the fields the user changed on their own profile.

        Args:
            user_id: The signed-in user's ID.
            email: New address, or None to keep the current one.
            username: New display name; an empty string clears it.

        Returns:
            Optional[User]: The updated user, or None when the id is gone.
        """
        async with get_async_session() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            if email is not None:
                user.email = email
            if username is not None:
                user.username = username.strip() or None
            session.add(user)
            await session.flush()
            await session.refresh(user)
            logger.info("user_profile_updated", user_id=user_id)
            return user

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email.

        Args:
            email: The email of the user to retrieve

        Returns:
            Optional[User]: The user if found, None otherwise
        """
        async with get_async_session() as session:
            statement = select(User).where(User.email == email)
            user = (await session.execute(statement)).scalars().first()
            return user

    async def revoke_refresh_tokens(self, user_id: int) -> bool:
        """Reject every refresh token issued for the user before now.

        Args:
            user_id: The user logging out.

        Returns:
            bool: True when the user existed and was stamped.
        """
        async with get_async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return False
            user.refresh_revoked_at = utc_now()
            session.add(user)
            await session.flush()
            logger.info("refresh_tokens_revoked", user_id=user_id)
            return True

    async def delete_user_by_email(self, email: str) -> bool:
        """按邮箱删除用户，连带清理其全部业务数据与 LangGraph checkpoints.

        删除顺序按外键依赖排（先子表后父表）；会话行删除后，再把每个
        会话线程的 checkpoint 表记录一并清掉（best-effort），避免对话
        内容成为孤儿。

        Args:
            email: The email of the user to delete

        Returns:
            bool: True if deletion was successful, False if user not found
        """
        async with get_async_session() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalars().first()
            if not user:
                return False

            thread_ids = list(
                (await session.execute(select(ChatSession.id).where(col(ChatSession.user_id) == user.id)))
                .scalars()
                .all()
            )
            user_id = user.id

            # ---- 业务数据：按 FK 依赖从子表到父表 ----
            await session.execute(
                delete(WatchlistGroupItem).where(
                    col(WatchlistGroupItem.group_id).in_(
                        select(WatchlistGroup.id).where(col(WatchlistGroup.user_id) == user_id)
                    )
                )
            )
            await session.execute(delete(WatchlistGroup).where(col(WatchlistGroup.user_id) == user_id))
            await session.execute(delete(Watchlist).where(col(Watchlist.user_id) == user_id))

            await session.execute(delete(PortfolioTransaction).where(col(PortfolioTransaction.user_id) == user_id))
            await session.execute(delete(PortfolioPosition).where(col(PortfolioPosition.user_id) == user_id))
            await session.execute(delete(AutoInvestPlan).where(col(AutoInvestPlan.user_id) == user_id))

            await session.execute(
                delete(HoldingImportItem).where(
                    col(HoldingImportItem.import_id).in_(
                        select(HoldingImport.id).where(col(HoldingImport.user_id) == user_id)
                    )
                )
            )
            await session.execute(delete(HoldingImport).where(col(HoldingImport.user_id) == user_id))
            await session.execute(delete(PortfolioAccount).where(col(PortfolioAccount.user_id) == user_id))

            await session.execute(delete(ChatSession).where(col(ChatSession.user_id) == user_id))
            await session.delete(user)
            await session.flush()

        # ---- LangGraph checkpoint 与进程内摘要缓存（best-effort）----
        for thread_id in thread_ids:
            await state_store.delete_thread_checkpoints(thread_id)
            context_manager.forget_thread(thread_id)

        logger.info("user_deleted", email=email, sessions=len(thread_ids))
        return True

    async def create_session(
        self, session_id: str, user_id: int, name: str = "", username: str | None = None
    ) -> ChatSession:
        """Create a new chat session.

        Args:
            session_id: The ID for the new session
            user_id: The ID of the user who owns the session
            name: Optional name for the session (defaults to empty string)
            username: Display name copied from the user for LLM personalization

        Returns:
            ChatSession: The created session
        """
        async with get_async_session() as session:
            chat_session = ChatSession(id=session_id, user_id=user_id, name=name, username=username)
            session.add(chat_session)
            await session.flush()
            await session.refresh(chat_session)
            logger.info("session_created", session_id=session_id, user_id=user_id, name=name)
            return chat_session

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID.

        Args:
            session_id: The ID of the session to delete

        Returns:
            bool: True if deletion was successful, False if session not found
        """
        async with get_async_session() as session:
            chat_session = await session.get(ChatSession, session_id)
            if not chat_session:
                return False

            await session.delete(chat_session)
            await session.flush()
            logger.info("session_deleted", session_id=session_id)
            return True

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get a session by ID.

        Args:
            session_id: The ID of the session to retrieve

        Returns:
            Optional[ChatSession]: The session if found, None otherwise
        """
        async with get_async_session() as session:
            chat_session = await session.get(ChatSession, session_id)
            return chat_session

    async def get_user_sessions(self, user_id: int) -> List[ChatSession]:
        """取出某个用户的全部会话.

        Args:
            user_id: 用户的 ID

        Returns:
            List[ChatSession]: 该用户的会话列表，最近创建的排在最前面
        """
        async with get_async_session() as session:
            statement = (
                select(ChatSession)
                .where(col(ChatSession.user_id) == user_id)
                .order_by(col(ChatSession.created_at).desc())
            )
            sessions = (await session.execute(statement)).scalars().all()
            return list(sessions)

    async def update_session_name(self, session_id: str, name: str) -> ChatSession:
        """Update a session's name.

        Args:
            session_id: The ID of the session to update
            name: The new name for the session

        Returns:
            ChatSession: The updated session

        Raises:
            HTTPException: If session is not found
        """
        async with get_async_session() as session:
            chat_session = await session.get(ChatSession, session_id)
            if not chat_session:
                raise HTTPException(status_code=404, detail="Session not found")

            chat_session.name = name
            session.add(chat_session)
            await session.flush()
            await session.refresh(chat_session)
            logger.info("session_name_updated", session_id=session_id, name=name)
            return chat_session

    def get_session_maker(self) -> AsyncSession:
        """Get a session maker for creating database sessions.

        Returns:
            AsyncSession: A caller-owned async session
        """
        return async_session_factory()

    async def health_check(self) -> bool:
        """Check database connection health and export it as a metric.

        Returns:
            bool: True if database is healthy, False otherwise
        """
        try:
            async with get_async_session() as session:
                # Execute a simple query to check connection
                (await session.execute(select(1))).first()
                component_up.labels(component="postgresql").set(1)
                return True
        except Exception as e:
            component_up.labels(component="postgresql").set(0)
            logger.exception("database_health_check_failed", error=str(e))
            return False


# Create a singleton instance
database_service = DatabaseService()
