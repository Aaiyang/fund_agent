"""可选 PostgreSQL 回归测试；所有测试写入在外层事务结束时回滚.

显式设置 FUND_TEST_POSTGRES=true，并使用已迁移的开发数据库后运行本文件。
"""

import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_engine
from app.models.user import User
from app.repositories import user_llm_repository as repository_module
from app.services.llm.credentials import decrypt_key
from app.services.llm.user_profiles import DEFAULT_PROFILE_NAME, PersonalProfile, user_profile_service

pytestmark = pytest.mark.skipif(
    os.getenv("FUND_TEST_POSTGRES") != "true", reason="requires explicit PostgreSQL opt-in"
)


async def test_real_database_upsert_selection_and_user_isolation(monkeypatch):
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as db:
                users = [
                    User(
                        email=f"llm-fixture-{uuid4()}@example.invalid",
                        hashed_password="fixture-not-login",  # pragma: allowlist secret -- inert fixture, not a valid hash
                    )
                    for _ in range(2)
                ]
                db.add_all(users)
                await db.flush()
                first, second = (user.id for user in users)

                @asynccontextmanager
                async def isolated_session():
                    db.expire_all()
                    yield db
                    await db.flush()

                monkeypatch.setattr(repository_module, "get_async_session", isolated_session)
                profile = PersonalProfile(
                    name="postgres-fixture",
                    model="fixture-model",
                    base_url="https://fixture.example/v1",
                    api_key="fixture-private-key",  # pragma: allowlist secret -- test fixture
                )
                await user_profile_service.save_profiles(first, [profile])
                await user_profile_service.switch_profile(first, profile.name)
                assert (await user_profile_service.list_profiles(first)).active == profile.name
                assert (await user_profile_service.list_profiles(second)).active == DEFAULT_PROFILE_NAME
                assert len((await user_profile_service.list_profiles(second)).profiles) == 1
                with pytest.raises(ValueError):
                    await user_profile_service.switch_profile(second, profile.name)
                ciphertext = (
                    await db.execute(text("SELECT profiles FROM user_llm_settings WHERE user_id = :id"), {"id": first})
                ).scalar_one()[0]
                assert "api_key" not in ciphertext
                assert decrypt_key(first, ciphertext["encrypted_api_key"]) == profile.api_key
                await user_profile_service.save_profiles(first, [])
                assert (await user_profile_service.list_profiles(first)).active == DEFAULT_PROFILE_NAME
        finally:
            if transaction.is_active:
                await transaction.rollback()
            await async_engine.dispose()
