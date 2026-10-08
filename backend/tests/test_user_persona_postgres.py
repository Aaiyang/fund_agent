"""真实 PostgreSQL 验证画像隔离、并发版本、确认幂等与清除；数据最终回滚."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core import database
from app.models.user import User
from app.models.user_persona import UserPersonaHistory
from app.repositories.user_persona_repository import (
    PersonaConflictError,
    PersonaLimitError,
    PersonaNotFoundError,
    user_persona_repository,
)
from app.schemas.user_persona import PersonaPatch
from app.services.user_persona_service import user_persona_service

pytestmark = pytest.mark.skipif(os.getenv("FUND_TEST_POSTGRES") != "true", reason="requires PostgreSQL opt-in")


@pytest.fixture
async def persona_database(monkeypatch):
    async with database.async_engine.connect() as connection:
        outer = await connection.begin()
        try:

            def factory():
                return AsyncSession(
                    bind=connection, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint"
                )

            monkeypatch.setattr(database, "async_session_factory", factory)
            async with database.get_async_session() as db:
                users = [
                    User(
                        email=f"persona-{uuid4()}@example.invalid",
                        hashed_password="fixture-not-login",  # pragma: allowlist secret -- inert test fixture
                    )
                    for _ in range(2)
                ]
                db.add_all(users)
                await db.flush()
                ids = [user.id for user in users]
            yield ids
        finally:
            await outer.rollback()
            await database.async_engine.dispose()


async def test_proposal_isolation_confirmation_idempotence_and_clear_tombstone(persona_database):
    owner, other = persona_database
    proposal = await user_persona_service.propose(
        owner, PersonaPatch(risk_preference="conservative"), "偏保守", "s", "m", "请记住我偏保守"
    )
    duplicate = await user_persona_service.propose(
        owner, PersonaPatch(risk_preference="conservative"), "偏保守", "s", "m", "请记住我偏保守"
    )
    assert duplicate.id == proposal.id
    assert (await user_persona_service.get(owner)).fields.risk_preference is None
    assert not (await user_persona_service.get(other)).pending_proposals
    with pytest.raises(PersonaNotFoundError):
        await user_persona_service.decide(other, proposal.id, "accept", 0)
    confirmed = await user_persona_service.decide(owner, proposal.id, "accept", 0)
    assert confirmed.revision == 1 and confirmed.fields.risk_preference == "conservative"
    assert confirmed.provenance["risk_preference"]["source_message_id"] == "m"
    repeated = await user_persona_service.decide(owner, proposal.id, "accept", 0)
    assert repeated.revision == 1
    assert len(await user_persona_service.history(owner, 20)) == 1
    cleared = await user_persona_service.clear(owner, 1)
    assert cleared.revision == 2 and not cleared.provenance and not cleared.pending_proposals
    assert cleared.fields.risk_preference is None
    assert await user_persona_service.history(owner, 20) == []
    with pytest.raises(PersonaNotFoundError):
        await user_persona_service.decide(owner, proposal.id, "accept", 2)
    with pytest.raises(PersonaConflictError):
        await user_persona_service.update(owner, PersonaPatch(risk_preference="aggressive"), 1)


async def test_direct_edit_supersedes_candidates_and_null_removes_only_one_field(persona_database):
    owner, _ = persona_database
    await user_persona_service.update(
        owner, PersonaPatch(risk_preference="conservative", response_detail="concise"), 0
    )
    proposal = await user_persona_service.propose(
        owner, PersonaPatch(risk_preference="aggressive"), "激进", "s", "m", "改成激进"
    )
    updated = await user_persona_service.update(owner, PersonaPatch(risk_preference=None), 1)
    assert updated.fields.risk_preference is None and updated.fields.response_detail == "concise"
    assert "risk_preference" not in updated.provenance and not updated.pending_proposals
    with pytest.raises(PersonaConflictError):
        await user_persona_service.decide(owner, proposal.id, "accept", 2)


async def test_profile_and_history_roll_back_on_mid_transaction_failure(persona_database, monkeypatch):
    owner, _ = persona_database
    await user_persona_service.update(owner, PersonaPatch(response_detail="concise"), 0)
    original = user_persona_repository._apply

    async def fail(db, row, changes, source, proposal=None):
        await original(db, row, changes, source, proposal)
        await db.flush()
        raise RuntimeError("fixture failure after flush")

    monkeypatch.setattr(user_persona_repository, "_apply", fail)
    with pytest.raises(RuntimeError):
        await user_persona_service.update(owner, PersonaPatch(response_detail="detailed"), 1)
    result = await user_persona_service.get(owner)
    assert result.revision == 1 and result.fields.response_detail == "concise"
    async with database.get_async_session() as db:
        history = list(await db.scalars(select(UserPersonaHistory).where(col(UserPersonaHistory.user_id) == owner)))
    assert len(history) == 1


async def test_pending_quota_and_rejection_do_not_change_confirmed_profile(persona_database):
    owner, other = persona_database
    ids = []
    for index in range(20):
        proposal = await user_persona_service.propose(
            owner, PersonaPatch(response_detail="concise"), "简洁", "s", f"m-{index}", "请记住回答简洁"
        )
        ids.append(proposal.id)
    with pytest.raises(PersonaLimitError):
        await user_persona_service.propose(
            owner, PersonaPatch(response_detail="concise"), "简洁", "s", "extra", "回答简洁"
        )
    rejected = await user_persona_service.decide(owner, ids[0], "reject", 0)
    assert rejected.revision == 0 and rejected.fields.response_detail is None
    assert len(rejected.pending_proposals) == 19
    await user_persona_service.decide(owner, ids[0], "reject", 0)
    with pytest.raises(PersonaConflictError):
        await user_persona_service.decide(owner, ids[0], "accept", 0)
    assert await user_persona_service.history(owner, 20) == []
    assert not (await user_persona_service.get(other)).pending_proposals
