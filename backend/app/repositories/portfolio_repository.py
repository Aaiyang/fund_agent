"""Portfolio repository: accounts, positions (optimistic lock), transactions."""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.analytics.positions import LedgerRow
from app.core.database import get_async_session
from app.models.holding_import import HoldingImport, HoldingImportItem
from app.models.portfolio import PortfolioAccount, PortfolioPosition, Transaction
from app.utils.clock import utc_now


class PortfolioRepository:
    """Async data access for accounts, positions and transactions."""

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    async def list_accounts(self, user_id: int) -> list[PortfolioAccount]:
        """List the user's accounts by creation order."""
        async with get_async_session() as session:
            result = await session.execute(
                select(PortfolioAccount)
                .where(col(PortfolioAccount.user_id) == user_id)
                .order_by(col(PortfolioAccount.id))
            )
            return list(result.scalars().all())

    async def get_account(self, user_id: int, account_id: int) -> PortfolioAccount | None:
        """Load one account owned by the user."""
        async with get_async_session() as session:
            result = await session.execute(
                select(PortfolioAccount).where(
                    col(PortfolioAccount.id) == account_id, col(PortfolioAccount.user_id) == user_id
                )
            )
            return result.scalar_one_or_none()

    async def find_account_by_name(
        self, user_id: int, name: str, exclude_id: int | None = None
    ) -> PortfolioAccount | None:
        """Load an account whose name matches, ignoring case and padding.

        The unique constraint compares bytes, so "支付宝" and "支付宝 " would
        both land; the service uses this to reject the near-duplicate first.
        """
        async with get_async_session() as session:
            statement = select(PortfolioAccount).where(
                col(PortfolioAccount.user_id) == user_id,
                func.lower(PortfolioAccount.name) == name.strip().lower(),
            )
            if exclude_id is not None:
                statement = statement.where(col(PortfolioAccount.id) != exclude_id)
            return (await session.execute(statement)).scalar_one_or_none()

    async def create_account(
        self,
        user_id: int,
        name: str,
        source_app: str | None,
        account_type: str,
        import_mode: str,
    ) -> PortfolioAccount:
        """Create a portfolio account."""
        async with get_async_session() as session:
            account = PortfolioAccount(
                user_id=user_id,
                name=name,
                source_app=source_app,
                account_type=account_type,
                import_mode=import_mode,
            )
            session.add(account)
            await session.flush()
            return account

    async def update_account(
        self,
        user_id: int,
        account_id: int,
        name: str | None = None,
        source_app: str | None = None,
    ) -> PortfolioAccount | None:
        """Rename an account or change its source label."""
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(PortfolioAccount).where(
                        col(PortfolioAccount.id) == account_id, col(PortfolioAccount.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                return None
            if name is not None:
                account.name = name
            if source_app is not None:
                account.source_app = source_app
            session.add(account)
            await session.flush()
            return account

    async def delete_account(self, user_id: int, account_id: int) -> bool:
        """Delete an account with its positions, transactions and import records."""
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(PortfolioAccount).where(
                        col(PortfolioAccount.id) == account_id, col(PortfolioAccount.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                return False
            import_ids = (
                (
                    await session.execute(
                        select(col(HoldingImport.id)).where(col(HoldingImport.account_id) == account_id)
                    )
                )
                .scalars()
                .all()
            )
            if import_ids:
                await session.execute(
                    sa_delete(HoldingImportItem).where(col(HoldingImportItem.import_id).in_(import_ids))
                )
                await session.execute(sa_delete(HoldingImport).where(col(HoldingImport.account_id) == account_id))
            await session.execute(sa_delete(Transaction).where(col(Transaction.account_id) == account_id))
            await session.execute(sa_delete(PortfolioPosition).where(col(PortfolioPosition.account_id) == account_id))
            await session.delete(account)
            return True

    async def touch_account_imported(self, user_id: int, account_id: int) -> None:
        """Set last_imported_at to now after a confirmed import."""
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(PortfolioAccount).where(
                        col(PortfolioAccount.id) == account_id, col(PortfolioAccount.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if account is not None:
                account.last_imported_at = utc_now()
                session.add(account)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def list_positions(self, user_id: int, account_id: int | None = None) -> list[PortfolioPosition]:
        """List positions, optionally scoped to one account."""
        async with get_async_session() as session:
            statement = select(PortfolioPosition).where(col(PortfolioPosition.user_id) == user_id)
            if account_id is not None:
                statement = statement.where(col(PortfolioPosition.account_id) == account_id)
            result = await session.execute(statement.order_by(col(PortfolioPosition.fund_code)))
            return list(result.scalars().all())

    async def get_position(self, user_id: int, account_id: int, fund_code: str) -> PortfolioPosition | None:
        """Load one position by (account, fund)."""
        async with get_async_session() as session:
            result = await session.execute(
                select(PortfolioPosition).where(
                    col(PortfolioPosition.user_id) == user_id,
                    col(PortfolioPosition.account_id) == account_id,
                    col(PortfolioPosition.fund_code) == fund_code,
                )
            )
            return result.scalar_one_or_none()

    async def _select_position(
        self, session: AsyncSession, user_id: int, account_id: int, fund_code: str
    ) -> PortfolioPosition | None:
        """Load one position inside an open session."""
        result = await session.execute(
            select(PortfolioPosition).where(
                col(PortfolioPosition.user_id) == user_id,
                col(PortfolioPosition.account_id) == account_id,
                col(PortfolioPosition.fund_code) == fund_code,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_position(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        expected_version: int | None,
        shares: float | None = None,
        cost_amount: float | None = None,
        average_cost_nav: float | None = None,
        market_value: float | None = None,
        profit_loss: float | None = None,
        purchase_date: date | None = None,
        reset: Sequence[str] = (),
    ) -> PortfolioPosition | None:
        """Insert or update a position with optimistic locking.

        Args:
            user_id: Owner id.
            account_id: Target account id.
            fund_code: The 6-digit fund code.
            expected_version: Caller's observed version. Required for updates;
                None on first insert. A mismatch returns None (→ HTTP 409).
            shares: Held shares.
            cost_amount: Cost basis in currency.
            average_cost_nav: Cost per unit NAV.
            market_value: Current market value.
            profit_loss: Accumulated profit/loss.
            purchase_date: 首次购买确认日, the day 持有天数 counts from.
            reset: Column names to blank out after applying the values above,
                returning each figure to its derived path.

        Returns:
            The updated position, or None on version conflict / missing row.

        A None field means "not supplied" and leaves an existing value intact:
        spec 3.7.1 allows partial snapshots and forbids fabricating data.
        """
        async with get_async_session() as session:
            existing = await self._select_position(session, user_id, account_id, fund_code)

            if existing is None:
                if expected_version is not None:
                    return None  # caller expected an existing row — treat as conflict
                statement = pg_insert(PortfolioPosition).values(
                    user_id=user_id,
                    account_id=account_id,
                    fund_code=fund_code,
                    shares=shares,
                    cost_amount=cost_amount,
                    average_cost_nav=average_cost_nav,
                    market_value=market_value,
                    profit_loss=profit_loss,
                    purchase_date=purchase_date,
                    version=1,
                    updated_at=utc_now(),
                    created_at=utc_now(),
                )
                created = (
                    await session.execute(statement.on_conflict_do_nothing(constraint="uq_position_account_fund"))
                ).rowcount
                if created:
                    return await self._select_position(session, user_id, account_id, fund_code)
                # A concurrent first write won the race; update that row instead
                # of raising the unique constraint as a 500.
                existing = await self._select_position(session, user_id, account_id, fund_code)
                if existing is None:
                    return None

            if expected_version is not None and existing.version != expected_version:
                return None  # optimistic lock conflict

            supplied = {
                "shares": shares,
                "cost_amount": cost_amount,
                "average_cost_nav": average_cost_nav,
                "market_value": market_value,
                "profit_loss": profit_loss,
                "purchase_date": purchase_date,
            }
            for key, value in supplied.items():
                if value is not None:
                    setattr(existing, key, value)
            # `reset` is how a caller says "put this figure back on the derived
            # path"; the keys are checked against the same set so no column can
            # be blanked by name alone.
            for key in reset:
                if key in supplied:
                    setattr(existing, key, None)
            existing.version = (existing.version or 1) + 1
            existing.updated_at = utc_now()
            session.add(existing)
            await session.flush()
            return existing

    async def delete_position(self, user_id: int, account_id: int, fund_code: str) -> bool:
        """Remove one position row."""
        async with get_async_session() as session:
            existing = (
                await session.execute(
                    select(PortfolioPosition).where(
                        col(PortfolioPosition.user_id) == user_id,
                        col(PortfolioPosition.account_id) == account_id,
                        col(PortfolioPosition.fund_code) == fund_code,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                return False
            await session.delete(existing)
            return True

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    async def list_transactions(
        self,
        user_id: int,
        account_id: int | None = None,
        fund_code: str | None = None,
        limit: int = 200,
    ) -> list[Transaction]:
        """List transactions newest first with optional account/fund filters."""
        async with get_async_session() as session:
            statement = select(Transaction).where(col(Transaction.user_id) == user_id)
            if account_id is not None:
                statement = statement.where(col(Transaction.account_id) == account_id)
            if fund_code is not None:
                statement = statement.where(col(Transaction.fund_code) == fund_code)
            statement = statement.order_by(col(Transaction.trade_date).desc(), col(Transaction.id).desc()).limit(limit)
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def ledger_rows(self, user_id: int, account_id: int | None = None) -> dict[tuple[int, str], list[LedgerRow]]:
        """Group every BUY/SELL row by (account, fund) in trade order.

        The whole ledger in one read: projecting a fund means walking every one
        of its rows, because a partial sell carries cost out at the average the
        holding was carried at. An OPENING row is the snapshot the ledger was
        started from and adds like a buy. Adjustment rows are excluded — they
        record a snapshot overwrite, not a trade.
        """
        async with get_async_session() as session:
            statement = (
                select(Transaction)
                .where(
                    col(Transaction.user_id) == user_id,
                    col(Transaction.transaction_type).in_(("OPENING", "BUY", "SELL")),
                )
                .order_by(col(Transaction.trade_date), col(Transaction.id))
            )
            if account_id is not None:
                statement = statement.where(col(Transaction.account_id) == account_id)
            result = await session.execute(statement)
            grouped: dict[tuple[int, str], list[LedgerRow]] = {}
            for row in result.scalars().all():
                grouped.setdefault((row.account_id, row.fund_code), []).append(
                    LedgerRow(
                        kind="SELL" if row.transaction_type == "SELL" else "BUY",
                        shares=row.shares or 0.0,
                        amount=row.amount or 0.0,
                    )
                )
            return grouped

    async def earliest_confirm_date(self, user_id: int, account_id: int, fund_code: str) -> date | None:
        """The first purchase's confirm day, which is where 持有天数 starts."""
        async with get_async_session() as session:
            statement = (
                select(col(Transaction.confirm_date))
                .where(
                    col(Transaction.user_id) == user_id,
                    col(Transaction.account_id) == account_id,
                    col(Transaction.fund_code) == fund_code,
                    col(Transaction.transaction_type).in_(("OPENING", "BUY")),
                    col(Transaction.confirm_date).is_not(None),
                )
                .order_by(col(Transaction.confirm_date))
                .limit(1)
            )
            return (await session.execute(statement)).scalar_one_or_none()

    async def add_transaction(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        transaction_type: str,
        trade_date: date,
        confirm_date: date | None = None,
        shares: float | None = None,
        nav: float | None = None,
        amount: float | None = None,
        fee: float | None = None,
        source: str = "manual",
        external_transaction_id: str | None = None,
    ) -> Transaction:
        """Append an audit/transaction record."""
        async with get_async_session() as session:
            record = Transaction(
                user_id=user_id,
                account_id=account_id,
                fund_code=fund_code,
                transaction_type=transaction_type,
                trade_date=trade_date,
                confirm_date=confirm_date,
                shares=shares,
                nav=nav,
                amount=amount,
                fee=fee,
                source=source,
                external_transaction_id=external_transaction_id,
            )
            session.add(record)
            await session.flush()
            return record


portfolio_repository = PortfolioRepository()
