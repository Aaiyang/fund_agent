"""真实 PostgreSQL 验证持仓确认的事务回滚、复核指纹和幂等性；测试数据全部回滚."""

import os
from datetime import date, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core import database
from app.models.holding_import import HoldingImport, HoldingImportItem
from app.models.portfolio import PortfolioAccount, PortfolioPosition, Transaction
from app.models.user import User
from app.repositories.import_repository import import_repository
from app.repositories.portfolio_repository import portfolio_repository
from app.services.holding_import_service import ImportStateError, holding_import_service
from app.services.agent_holding_import_service import agent_holding_import_service
from app.services import holding_import_service as holding_module
from app.utils.clock import utc_now
from app.utils.holding_review import holding_review_digest

pytestmark = pytest.mark.skipif(os.getenv("FUND_TEST_POSTGRES") != "true", reason="requires PostgreSQL opt-in")


@pytest.fixture
async def database_import(monkeypatch):
    async with database.async_engine.connect() as connection:
        outer = await connection.begin()
        try:

            def factory():
                return AsyncSession(
                    bind=connection, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint"
                )

            monkeypatch.setattr(database, "async_session_factory", factory)
            async with database.get_async_session() as db:
                user = User(
                    email=f"holding-fixture-{uuid4()}@example.invalid",
                    hashed_password="fixture-not-login",  # pragma: allowlist secret -- inert fixture
                )
                db.add(user)
                await db.flush()
                account = PortfolioAccount(user_id=user.id, name="fixture account")
                db.add(account)
                await db.flush()
                record = HoldingImport(
                    user_id=user.id,
                    account_id=account.id,
                    import_type="SCREENSHOT",
                    status="REVIEW_REQUIRED",
                    image_count=1,
                    items_detected=2,
                )
                db.add(record)
                await db.flush()
                db.add(
                    PortfolioPosition(
                        user_id=user.id,
                        account_id=account.id,
                        fund_code="000001",
                        market_value=50,
                        shares=5,
                        purchase_date=date(2021, 1, 4),
                    )
                )
                for code, amount in [("000001", 1000), ("000002", 2000)]:
                    db.add(
                        HoldingImportItem(
                            import_id=record.id,
                            matched_fund_code=code,
                            market_value=amount,
                            shares=10,
                            validation_status="ok",
                        )
                    )
            cleanups = []

            async def cleanup(import_id):
                cleanups.append(import_id)

            monkeypatch.setattr(holding_import_service, "_cleanup_images", cleanup)
            yield user.id, account.id, record.id, cleanups
        finally:
            await outer.rollback()
            await database.async_engine.dispose()


async def test_confirm_rolls_back_all_positions_and_audit_on_mid_batch_failure(database_import, monkeypatch):
    user_id, account_id, import_id, cleanups = database_import
    original = portfolio_repository.add_transaction
    calls = []

    async def failing_audit(**kwargs):
        result = await original(**kwargs)
        calls.append(result)
        if len(calls) == 2:
            raise RuntimeError("fixture mid batch failure")
        return result

    monkeypatch.setattr(portfolio_repository, "add_transaction", failing_audit)
    with pytest.raises(RuntimeError, match="mid batch"):
        await holding_import_service.confirm_import(user_id, import_id)
    positions = await portfolio_repository.list_positions(user_id, account_id)
    assert len(positions) == 1 and positions[0].market_value == 50 and positions[0].version == 1
    assert (await import_repository.get_import(user_id, import_id)).status == "REVIEW_REQUIRED"
    async with database.get_async_session() as db:
        count = (
            await db.execute(select(func.count()).select_from(Transaction).where(col(Transaction.user_id) == user_id))
        ).scalar_one()
    assert count == 0 and cleanups == []


async def test_confirm_requires_current_snapshot_and_applies_only_once(database_import):
    user_id, account_id, import_id, cleanups = database_import
    with pytest.raises(ImportStateError, match="import_review_changed"):
        await holding_import_service.confirm_import(user_id, import_id, expected_review_digest="0" * 64)
    detail = await holding_import_service.get_import_detail(user_id, import_id)
    digest = holding_review_digest(detail)
    first = await holding_import_service.confirm_import(user_id, import_id, expected_review_digest=digest)
    second = await holding_import_service.confirm_import(user_id, import_id, expected_review_digest=digest)
    assert first == second == {"applied": 2, "skipped": 0}
    positions = await portfolio_repository.list_positions(user_id, account_id)
    assert [position.market_value for position in positions] == [1000, 2000]
    assert positions[0].version == 2 and positions[0].purchase_date == date(2021, 1, 4)
    assert (await import_repository.get_import(user_id, import_id)).status == "APPLIED"
    async with database.get_async_session() as db:
        count = (
            await db.execute(select(func.count()).select_from(Transaction).where(col(Transaction.user_id) == user_id))
        ).scalar_one()
    assert count == 2 and cleanups == [import_id, import_id]


async def test_staged_recognition_starts_once_and_uses_actual_start_time(database_import, monkeypatch):
    user_id, account_id, import_id, cleanups = database_import
    async with database.transaction_scope():
        record = await import_repository.get_import(user_id, import_id, for_update=True)
        record.status = "UPLOADED"
        record.chat_session_id = f"fixture-{uuid4().hex}"
        record.account_id = None
        record.started_at = utc_now() - timedelta(hours=1)
    before = utc_now()
    enqueue = AsyncMock()
    monkeypatch.setattr(holding_module, "enqueue", enqueue)
    await holding_import_service.start_screenshot_import(user_id, import_id)
    await holding_import_service.start_screenshot_import(user_id, import_id)
    record = await import_repository.get_import(user_id, import_id)
    assert record.status == "PARSING" and record.started_at >= before
    assert record.account_id is None and cleanups == []
    enqueue.assert_awaited_once()


async def test_unassigned_agent_draft_persists_and_selection_precedes_confirmation(database_import):
    user_id, account_id, import_id, cleanups = database_import
    session_id = f"fixture-{uuid4().hex}"
    async with database.transaction_scope():
        record = await import_repository.get_import(user_id, import_id, for_update=True)
        record.account_id = None
        record.chat_session_id = session_id
    assert (await import_repository.get_import(user_id, import_id)).account_id is None
    with pytest.raises(ImportStateError, match="import_account_required"):
        await holding_import_service.confirm_import(user_id, import_id)
    await agent_holding_import_service.select_account(user_id, session_id, import_id, account_id)
    detail = await agent_holding_import_service.detail(user_id, session_id, import_id)
    assert detail.account_id == account_id and detail.status == "REVIEW_REQUIRED"
    positions = await portfolio_repository.list_positions(user_id, account_id)
    assert len(positions) == 1 and positions[0].market_value == 50 and cleanups == []
    review = await agent_holding_import_service.review(user_id, session_id, import_id)
    result = await agent_holding_import_service.decide(
        user_id, session_id, import_id, decision="confirm", review_digest=review.review_digest
    )
    assert result["applied"] == 2
    assert (await import_repository.get_import(user_id, import_id)).status == "APPLIED"
