"""可选 PostgreSQL CAS 回归；写入全部在外层事务结束时回滚."""

import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import state_store
from app.agent.context.manager import ContextManager
from app.agent.context.state_store import load_context_state as database_load
from app.agent.context.state_store import save_context_state as database_save
from app.agent.context.summary import ConversationSummaryManager
from app.core.database import async_engine
from app.models.session import Session
from app.models.user import User

pytestmark = pytest.mark.skipif(
    os.getenv("FUND_TEST_POSTGRES") != "true", reason="requires explicit PostgreSQL opt-in"
)


async def test_database_cas_clear_and_legacy_backup(monkeypatch):
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as db:
                user = User(
                    email=f"summary-fixture-{uuid4()}@example.invalid",
                    hashed_password="fixture-not-login",  # pragma: allowlist secret -- inert fixture
                )
                db.add(user)
                await db.flush()
                legacy = {"version": 1, "segments": [{"covered_turn_count": 999}], "epoch_sequence": 9}
                session = Session(
                    id=f"summary-{uuid4()}", user_id=user.id, context_state=legacy, context_state_legacy=legacy
                )
                db.add(session)
                await db.flush()
                session_id = session.id

                @asynccontextmanager
                async def isolated_session():
                    db.expire_all()
                    yield db
                    await db.flush()

                monkeypatch.setattr(state_store, "get_async_session", isolated_session)
                restored = await database_load(session_id)
                assert restored.segments == [] and restored.revision == 0

                async def summarize(_messages):
                    return "事实摘要"

                executor = ConversationSummaryManager(summarize)
                turns = ContextManager._group_messages_into_turns(
                    [HumanMessage(content="question", id="u"), AIMessage(content="answer", id="a")]
                )
                result = await executor.compact(
                    turns=turns, source_start=0, version=1, input_token_limit=2000, output_token_limit=100
                )
                assert await database_save(session_id, [result.summary], 2, expected_revision=0)
                assert not await database_save(session_id, [], 1, expected_revision=0)
                saved = await database_load(session_id)
                assert saved.segments == [result.summary] and saved.revision == 1
                backup = (
                    await db.execute(
                        text('SELECT context_state_legacy FROM "session" WHERE id = :id'), {"id": session_id}
                    )
                ).scalar_one()
                assert backup == legacy
                # 与生产 clear_chat_history 相同的修订号递增，拒绝清空前启动的旧 writer。
                await db.execute(
                    text(
                        'UPDATE "session" SET context_state = NULL, context_state_legacy = NULL, '
                        "context_revision = context_revision + 1 WHERE id = :id"
                    ),
                    {"id": session_id},
                )
                assert not await database_save(session_id, [result.summary], 2, expected_revision=1)
                cleared = await database_load(session_id)
                assert cleared.segments == [] and cleared.revision == 2
                assert not await database_save("nonexistent-session", [result.summary], 2, expected_revision=0)
        finally:
            if transaction.is_active:
                await transaction.rollback()
            await async_engine.dispose()
