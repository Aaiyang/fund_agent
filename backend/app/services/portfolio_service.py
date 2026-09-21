"""Portfolio domain service: accounts, positions, summary, transactions.

Derived metrics (rates, daily P/L, position ratio) are computed at query time
from stored snapshots + latest NAVs — never persisted, so they can't drift
(MVP spec 12.8). All future agents/tools must go through this service.
"""

from datetime import datetime

from app.core.logging import logger
from app.models.portfolio import PortfolioAccount, PortfolioPosition
from app.repositories.fund_repository import fund_repository
from app.repositories.portfolio_repository import portfolio_repository
from app.schemas.portfolio import (
    AccountItem,
    PortfolioSummary,
    PositionItem,
    TransactionItem,
)
from app.utils.clock import business_today


class PositionConflictError(Exception):
    """Optimistic lock failure — another writer updated the position first."""


class AccountNotFoundError(Exception):
    """The account does not exist or belongs to another user (spec 16 isolation)."""


class PortfolioService:
    """Async portfolio operations."""

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    async def ensure_account(self, user_id: int, account_id: int) -> PortfolioAccount:
        """Return the account or raise when it is not the caller's.

        Every account-scoped write and every explicit-account read goes
        through here; positions/transactions are keyed by account_id and the
        repository cannot tell a foreign account from an empty result.
        """
        account = await portfolio_repository.get_account(user_id, account_id)
        if account is None:
            raise AccountNotFoundError(f"portfolio account {account_id} not found")
        return account

    async def list_accounts(self, user_id: int) -> list[AccountItem]:
        """List accounts with import status."""
        accounts = await portfolio_repository.list_accounts(user_id)
        return [self._account_item(account) for account in accounts]

    async def create_account(
        self,
        user_id: int,
        name: str,
        source_app: str | None,
        account_type: str,
        import_mode: str,
    ) -> AccountItem:
        """Create an account."""
        account = await portfolio_repository.create_account(user_id, name, source_app, account_type, import_mode)
        logger.info("portfolio_account_created", user_id=user_id, account_id=account.id)
        return self._account_item(account)

    async def update_account(
        self,
        user_id: int,
        account_id: int,
        name: str | None,
        source_app: str | None,
    ) -> AccountItem | None:
        """Rename an account / change its source label."""
        account = await portfolio_repository.update_account(user_id, account_id, name, source_app)
        return self._account_item(account) if account else None

    async def delete_account(self, user_id: int, account_id: int) -> bool:
        """Delete an account and everything under it."""
        deleted = await portfolio_repository.delete_account(user_id, account_id)
        logger.info("portfolio_account_deleted", user_id=user_id, account_id=account_id, deleted=deleted)
        return deleted

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def list_positions(self, user_id: int, account_id: int | None = None) -> list[PositionItem]:
        """List positions with derived metrics and fund names."""
        if account_id is not None:
            await self.ensure_account(user_id, account_id)
        positions = await portfolio_repository.list_positions(user_id, account_id)
        total_value = sum(p.market_value or 0.0 for p in positions) or 0.0
        items = []
        for position in positions:
            items.append(await self._position_item(position, total_value))
        return items

    async def get_position(self, user_id: int, account_id: int, fund_code: str) -> PositionItem | None:
        """One position with derived metrics (spec 3.5.2 fields)."""
        await self.ensure_account(user_id, account_id)
        position = await portfolio_repository.get_position(user_id, account_id, fund_code)
        if position is None:
            return None
        siblings = await portfolio_repository.list_positions(user_id, account_id)
        total_value = sum(p.market_value or 0.0 for p in siblings)
        item = await self._position_item(position, total_value)
        first_activity = await portfolio_repository.first_activity_date(user_id, account_id, fund_code)
        if first_activity is not None:
            item.holding_days = (business_today() - first_activity).days
        return item

    async def upsert_position(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        expected_version: int | None = None,
        **fields: float | None,
    ) -> PositionItem:
        """Create or update a position snapshot with optimistic locking.

        Raises:
            AccountNotFoundError: unknown or foreign account → HTTP 404.
            PositionConflictError: version mismatch → HTTP 409 upstream.
        """
        await self.ensure_account(user_id, account_id)
        updated = await portfolio_repository.upsert_position(
            user_id, account_id, fund_code, expected_version, **fields
        )
        if updated is None:
            raise PositionConflictError(f"position version conflict for fund {fund_code}; reload and retry")
        await portfolio_repository.add_transaction(
            user_id=user_id,
            account_id=account_id,
            fund_code=fund_code,
            transaction_type="MANUAL_ADJUSTMENT",
            trade_date=business_today(),
            shares=updated.shares,
            nav=updated.average_cost_nav,
            amount=updated.market_value,
            source="manual",
        )
        logger.info(
            "position_upserted",
            user_id=user_id,
            account_id=account_id,
            fund_code=fund_code,
            version=updated.version,
        )
        account_positions = await portfolio_repository.list_positions(user_id, account_id)
        total_value = sum(p.market_value or 0.0 for p in account_positions)
        return await self._position_item(updated, total_value)

    async def delete_position(self, user_id: int, account_id: int, fund_code: str) -> bool:
        """Remove a position and write an audit adjustment."""
        await self.ensure_account(user_id, account_id)
        deleted = await portfolio_repository.delete_position(user_id, account_id, fund_code)
        if deleted:
            await portfolio_repository.add_transaction(
                user_id=user_id,
                account_id=account_id,
                fund_code=fund_code,
                transaction_type="MANUAL_ADJUSTMENT",
                trade_date=business_today(),
                source="manual",
            )
        return deleted

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    async def get_summary(self, user_id: int, account_id: int | None = None) -> PortfolioSummary:
        """Aggregate asset summary: total value, P/L, daily P/L (spec 3.2)."""
        if account_id is not None:
            await self.ensure_account(user_id, account_id)
        positions = await portfolio_repository.list_positions(user_id, account_id)
        summary = PortfolioSummary(fund_count=len(positions))
        latest_at: datetime | None = None

        for position in positions:
            summary.total_market_value += position.market_value or 0.0
            summary.total_cost += position.cost_amount or 0.0
            summary.total_profit_loss += position.profit_loss or 0.0
            latest = await fund_repository.get_latest_nav(position.fund_code)
            if latest is not None:
                daily = (latest.daily_return or 0.0) * (position.market_value or 0.0) / 100.0
                summary.daily_profit_loss += daily
                if latest.fetched_at and (latest_at is None or latest.fetched_at > latest_at):
                    latest_at = latest.fetched_at

        if summary.total_cost > 0:
            summary.total_profit_loss_rate = summary.total_profit_loss / summary.total_cost
        summary.data_updated_at = latest_at
        return summary

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    async def list_transactions(
        self,
        user_id: int,
        account_id: int | None = None,
        fund_code: str | None = None,
    ) -> list[TransactionItem]:
        """List transactions with fund names."""
        if account_id is not None:
            await self.ensure_account(user_id, account_id)
        records = await portfolio_repository.list_transactions(user_id, account_id, fund_code)
        items = []
        for record in records:
            fund = await fund_repository.get_fund(record.fund_code)
            items.append(
                TransactionItem(
                    id=record.id or 0,
                    account_id=record.account_id,
                    fund_code=record.fund_code,
                    fund_name=fund.fund_name if fund else None,
                    transaction_type=record.transaction_type,
                    trade_date=record.trade_date,
                    shares=record.shares,
                    nav=record.nav,
                    amount=record.amount,
                    fee=record.fee,
                    source=record.source,
                    external_transaction_id=record.external_transaction_id,
                    created_at=record.created_at,
                )
            )
        return items

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _position_item(self, position: PortfolioPosition, total_value: float) -> PositionItem:
        """Enrich a stored position with query-time derived metrics."""
        fund = await fund_repository.get_fund(position.fund_code)
        latest = await fund_repository.get_latest_nav(position.fund_code)

        profit_loss_rate = None
        if position.profit_loss is not None and position.cost_amount:
            profit_loss_rate = position.profit_loss / position.cost_amount

        daily_profit_loss = None
        daily_return = latest.daily_return if latest else None
        if latest and latest.daily_return is not None and position.market_value:
            daily_profit_loss = latest.daily_return * position.market_value / 100.0

        position_ratio = None
        if total_value > 0 and position.market_value is not None:
            position_ratio = position.market_value / total_value

        return PositionItem(
            id=position.id,
            account_id=position.account_id,
            fund_code=position.fund_code,
            fund_name=fund.fund_name if fund else None,
            shares=position.shares,
            cost_amount=position.cost_amount,
            average_cost_nav=position.average_cost_nav,
            market_value=position.market_value,
            profit_loss=position.profit_loss,
            profit_loss_rate=profit_loss_rate,
            daily_profit_loss=daily_profit_loss,
            daily_return=daily_return,
            position_ratio=position_ratio,
            nav_date=latest.nav_date if latest else None,
            is_updated=latest is not None,
            version=position.version or 1,
            updated_at=position.updated_at,
        )

    @staticmethod
    def _account_item(account) -> AccountItem:
        """Map an account row to its schema."""
        return AccountItem(
            id=account.id or 0,
            name=account.name,
            source_app=account.source_app,
            account_type=account.account_type,
            import_mode=account.import_mode,
            last_imported_at=account.last_imported_at,
            created_at=account.created_at,
        )


portfolio_service = PortfolioService()
