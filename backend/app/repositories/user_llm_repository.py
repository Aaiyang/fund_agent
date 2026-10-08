"""个人模型配置的异步仓储，所有查询均限定 user_id."""

from sqlalchemy.dialects.postgresql import insert

from app.core.database import get_async_session
from app.models.user_llm_settings import UserLlmSettings
from app.utils.clock import utc_now


class UserLlmRepository:
    """持久化用户个人配置，每个用户一条记录."""

    async def get(self, user_id: int) -> UserLlmSettings | None:
        """只读取指定用户的配置."""
        async with get_async_session() as db:
            return await db.get(UserLlmSettings, user_id)

    async def save(self, user_id: int, profiles: list[dict[str, str]], active: str) -> None:
        """在一次事务中更新档案列表及当前选择."""
        now = utc_now()
        stmt = insert(UserLlmSettings).values(
            user_id=user_id, profiles=profiles, active=active, created_at=now, updated_at=now
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"], set_={"profiles": profiles, "active": active, "updated_at": now}
        )
        async with get_async_session() as db:
            await db.execute(stmt)

    async def set_active(self, user_id: int, active: str) -> bool:
        """锁定该用户记录后切换，防止与同时保存的档案列表交叉覆盖."""
        async with get_async_session() as db:
            row = await db.get(UserLlmSettings, user_id, with_for_update=True)
            if row is None:
                return active == "默认 GLM Flash"
            if active != "默认 GLM Flash" and not any(profile["name"] == active for profile in row.profiles):
                return False
            row.active = active
            row.updated_at = utc_now()
            return True


user_llm_repository = UserLlmRepository()
