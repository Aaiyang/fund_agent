"""真实 PostgreSQL 验证并发更新、事务回滚及交易重放；只清理本测试创建的记录."""

import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlmodel import col

from app.core import database
from app.models.fund import Fund, FundNav
from app.models.portfolio import PortfolioAccount, PortfolioPosition, Transaction
from app.models.user import User
from app.models.session import Session as ChatSession
from app.repositories.portfolio_repository import portfolio_repository
from app.services.portfolio_service import portfolio_service, TradeIdempotencyConflictError, TradeTooLargeError
from app.services.database import database_service
from app.services.session_naming import _claim_session

pytestmark = pytest.mark.skipif(os.getenv("FUND_TEST_POSTGRES") != "true", reason="requires PostgreSQL opt-in")


@pytest.fixture
async def portfolio_data():
    codes = [uuid4().hex[:6], uuid4().hex[:6]]
    async with database.get_async_session() as db:
        user = User(email=f"write-fixture-{uuid4()}@example.invalid", hashed_password="not-a-login")
        db.add(user)
        await db.flush()
        account = PortfolioAccount(user_id=user.id, name="write fixture")
        db.add(account)
        await db.flush()
        for code in codes:
            db.add(Fund(fund_code=code, fund_name="write fixture"))
        await db.flush()
        for code in codes:
            db.add(FundNav(fund_code=code, nav_date=date(2026, 9, 30), unit_nav=1))
        db.add(
            PortfolioPosition(
                user_id=user.id,
                account_id=account.id,
                fund_code=codes[0],
                shares=100,
                cost_amount=100,
                market_value=100,
            )
        )
        user_id, account_id = user.id, account.id
    try:
        yield user_id, account_id, codes
    finally:
        async with database.get_async_session() as db:
            for model in (ChatSession, Transaction, PortfolioPosition, PortfolioAccount):
                await db.execute(delete(model).where(col(model.user_id) == user_id))
            await db.execute(delete(User).where(col(User.id) == user_id))
            await db.execute(delete(FundNav).where(col(FundNav.fund_code).in_(codes)))
            await db.execute(delete(Fund).where(col(Fund.fund_code).in_(codes)))
        await database.async_engine.dispose()


async def trade(data, *, key="fixture-order", operation="BUY", amount=10, shares=None):
    user, account, codes = data
    return await portfolio_service.record_trade(
        user,
        account,
        codes[0],
        operation,
        date(2026, 9, 30),
        False,
        amount=amount,
        shares=shares,
        target_code=codes[1] if operation == "CONVERT" else None,
        idempotency_key=key,
    )


async def test_same_version_allows_only_one_concurrent_update(portfolio_data):
    user, account, codes = portfolio_data
    results = await asyncio.gather(
        *[portfolio_repository.upsert_position(user, account, codes[0], 1, market_value=value) for value in (111, 222)]
    )
    assert sum(result is not None for result in results) == 1
    current = await portfolio_repository.get_position(user, account, codes[0])
    assert current.version == 2 and current.market_value in (111, 222)
    assert await portfolio_repository.upsert_position(user, account, codes[0], None, market_value=999) is None


async def test_simultaneous_first_create_does_not_overwrite_winner(portfolio_data):
    user, account, codes = portfolio_data
    results = await asyncio.gather(
        *[
            portfolio_repository.upsert_position(user, account, codes[1], None, market_value=value)
            for value in (111, 222)
        ]
    )
    assert sum(result is not None for result in results) == 1
    current = await portfolio_repository.get_position(user, account, codes[1])
    assert current.version == 1 and current.market_value in (111, 222)


@pytest.mark.parametrize("failure", ["second_leg", "projection"])
async def test_conversion_failure_rolls_back_opening_legs_and_positions(portfolio_data, monkeypatch, failure):
    user, account, codes = portfolio_data
    original = portfolio_repository.add_transaction

    async def fail_leg(**kwargs):
        result = await original(**kwargs)
        if kwargs["transaction_type"] == "CONVERT_IN":
            raise RuntimeError("fixture second leg")
        return result

    async def fail_projection(*args):
        raise RuntimeError("fixture projection")

    if failure == "second_leg":
        monkeypatch.setattr(portfolio_repository, "add_transaction", fail_leg)
    else:
        monkeypatch.setattr(portfolio_service, "_reproject", fail_projection)
    with pytest.raises(RuntimeError, match="fixture"):
        await trade(portfolio_data, operation="CONVERT", amount=None, shares=10)
    assert await portfolio_repository.ledger_rows(user, account) == {}
    positions = await portfolio_repository.list_positions(user, account)
    assert len(positions) == 1 and positions[0].shares == 100 and positions[0].version == 1


async def test_manual_audit_failure_rolls_back_position(portfolio_data, monkeypatch):
    user, account, codes = portfolio_data

    async def failed_audit(**kwargs):
        raise RuntimeError("fixture audit")

    monkeypatch.setattr(portfolio_repository, "add_transaction", failed_audit)
    with pytest.raises(RuntimeError, match="audit"):
        await portfolio_service.upsert_position(user, account, codes[0], expected_version=1, market_value=999)
    current = await portfolio_repository.get_position(user, account, codes[0])
    assert current.market_value == 100 and current.version == 1


async def test_concurrent_retries_record_a_single_trade_and_reject_changed_payload(portfolio_data):
    user, account, codes = portfolio_data
    first, second = await asyncio.gather(trade(portfolio_data), trade(portfolio_data))
    assert first.shares == second.shares == 110
    rows = await portfolio_repository.ledger_rows(user, account)
    assert len(rows[(account, codes[0])]) == 2  # 一条 OPENING + 一条 BUY
    with pytest.raises(TradeIdempotencyConflictError):
        await trade(portfolio_data, amount=20)
    assert (await portfolio_repository.get_position(user, account, codes[0])).shares == 110


async def test_concurrent_sales_cannot_oversell_or_duplicate_opening(portfolio_data):
    user, account, codes = portfolio_data
    results = await asyncio.gather(
        *[trade(portfolio_data, key=key, operation="SELL", amount=None, shares=80) for key in ("sell-a", "sell-b")],
        return_exceptions=True,
    )
    assert sum(isinstance(result, TradeTooLargeError) for result in results) == 1
    assert (await portfolio_repository.get_position(user, account, codes[0])).shares == 20
    assert len((await portfolio_repository.ledger_rows(user, account))[(account, codes[0])]) == 2


async def test_conversion_replay_does_not_repeat_either_leg(portfolio_data):
    user, account, codes = portfolio_data
    await trade(portfolio_data, operation="CONVERT", amount=None, shares=10)
    await trade(portfolio_data, operation="CONVERT", amount=None, shares=10)
    assert (await portfolio_repository.get_position(user, account, codes[0])).shares == 90
    assert (await portfolio_repository.get_position(user, account, codes[1])).shares == 10
    rows = await portfolio_repository.ledger_rows(user, account)
    assert len(rows[(account, codes[0])]) == 2 and len(rows[(account, codes[1])]) == 1


async def test_cancelled_trade_rolls_back_all_writes(portfolio_data, monkeypatch):
    user, account, codes = portfolio_data
    entered = asyncio.Event()

    async def wait_projection(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(portfolio_service, "_reproject", wait_projection)
    task = asyncio.create_task(trade(portfolio_data))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await portfolio_repository.ledger_rows(user, account) == {}
    assert (await portfolio_repository.get_position(user, account, codes[0])).shares == 100


async def test_idempotency_key_cannot_be_reused_for_another_account(portfolio_data):
    user, account, codes = portfolio_data
    await trade(portfolio_data)
    other = await portfolio_repository.create_account(user, "other fixture", None, "manual", "manual")
    with pytest.raises(TradeIdempotencyConflictError):
        await trade((user, other.id, codes))
    assert await portfolio_repository.ledger_rows(user, other.id) == {}


async def test_async_auth_session_crud_and_atomic_naming(portfolio_data):
    user, _, _ = portfolio_data
    session_id = f"write-fixture-{uuid4()}"
    owner = await database_service.get_user(user)
    assert (await database_service.get_user_by_email(owner.email)).id == user
    assert await database_service.health_check()
    await database_service.update_user(user, username="fixture")
    await database_service.create_session(session_id, user)
    claims = await asyncio.gather(_claim_session(session_id, "first"), _claim_session(session_id, "second"))
    assert sorted(claims) == [False, True]
    assert (await database_service.get_session(session_id)).name in ("first", "second")
    await database_service.update_session_name(session_id, "final")
    assert any(item.name == "final" for item in await database_service.get_user_sessions(user))
    assert await database_service.revoke_refresh_tokens(user)
    assert (await database_service.get_user(user)).refresh_revoked_at is not None
    assert await database_service.delete_session(session_id)
    assert await database_service.get_session(session_id) is None
