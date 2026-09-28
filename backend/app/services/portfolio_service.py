"""Portfolio domain service: accounts, positions, summary, transactions.

Derived metrics (rates, daily P/L, position ratio) are computed at query time
from stored snapshots + latest NAVs — never persisted, so they can't drift
(MVP spec 12.8). All future agents/tools must go through this service.
"""

import asyncio
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.analytics import period_return, window_return
from app.analytics.positions import position_figures
from app.analytics.returns import NavPoint
from app.analytics.settlement import settlement_date
from app.core.logging import logger
from app.models.fund import FundNav
from app.models.portfolio import PortfolioAccount, PortfolioPosition
from app.repositories.fund_repository import fund_repository
from app.repositories.portfolio_repository import portfolio_repository
from app.schemas.portfolio import (
    AccountItem,
    PortfolioSummary,
    PositionItem,
    PositionPreviewResponse,
    TransactionItem,
)
from app.utils.clock import business_today


class PositionConflictError(Exception):
    """Optimistic lock failure — another writer updated the position first."""


class AccountNotFoundError(Exception):
    """The account does not exist or belongs to another user (spec 16 isolation)."""


class AccountNameConflictError(Exception):
    """Another of the user's accounts already uses this name."""

    def __init__(self, name: str) -> None:
        """Keep the offending name so the route can echo it back."""
        super().__init__(name)
        self.name = name


_WEEKLY_DAYS = 7
_WINDOW_LOOKBACK_DAYS = 45


def period_profit_loss(market_value: float | None, fraction: float | None) -> float | None:
    """Money gained over a window, on the same base as 昨日收益.

    The daily column multiplies the *current* amount by the return rather than
    the start-of-window amount; one convention keeps the week/month/day columns
    from disagreeing by a rounding-sized gap.
    """
    if market_value is None or fraction is None:
        return None
    return market_value * fraction


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
        """Create an account; names are unique per user."""
        if await portfolio_repository.find_account_by_name(user_id, name) is not None:
            raise AccountNameConflictError(name)
        try:
            account = await portfolio_repository.create_account(user_id, name, source_app, account_type, import_mode)
        except IntegrityError as error:
            # Only a concurrent create can slip past the check above.
            raise AccountNameConflictError(name) from error
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
        if name is not None and await portfolio_repository.find_account_by_name(user_id, name, exclude_id=account_id):
            raise AccountNameConflictError(name)
        try:
            account = await portfolio_repository.update_account(user_id, account_id, name, source_app)
        except IntegrityError as error:
            raise AccountNameConflictError(name or "") from error
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
        histories = await self._recent_history([position.fund_code for position in positions])
        settled_navs = await self._settled_navs(positions)
        items = []
        for position in positions:
            items.append(
                await self._position_item(position, total_value, histories.get(position.fund_code), settled_navs)
            )
        return items

    async def get_position(self, user_id: int, account_id: int, fund_code: str) -> PositionItem | None:
        """One position with derived metrics (spec 3.5.2 fields)."""
        await self.ensure_account(user_id, account_id)
        position = await portfolio_repository.get_position(user_id, account_id, fund_code)
        if position is None:
            return None
        siblings = await portfolio_repository.list_positions(user_id, account_id)
        total_value = sum(p.market_value or 0.0 for p in siblings)
        histories = await self._recent_history([fund_code])
        settled_navs = await self._settled_navs([position])
        return await self._position_item(position, total_value, histories.get(fund_code), settled_navs)

    async def upsert_position(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        expected_version: int | None = None,
        purchase_date: date | None = None,
        purchase_after_cutoff: bool | None = None,
        reset: Sequence[str] = (),
        **fields: float | None,
    ) -> PositionItem:
        """Create or update a position snapshot with optimistic locking.

        Raises:
            AccountNotFoundError: unknown or foreign account → HTTP 404.
            PositionConflictError: version mismatch → HTTP 409 upstream.
        """
        await self.ensure_account(user_id, account_id)
        updated = await portfolio_repository.upsert_position(
            user_id,
            account_id,
            fund_code,
            expected_version,
            purchase_date=purchase_date,
            purchase_after_cutoff=purchase_after_cutoff,
            reset=reset,
            **fields,
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
        histories = await self._recent_history([fund_code])
        settled_navs = await self._settled_navs([updated])
        return await self._position_item(updated, total_value, histories.get(fund_code), settled_navs)

    async def preview_position(
        self, fund_code: str, purchase_date: date, after_cutoff: bool, market_value: float | None = None
    ) -> PositionPreviewResponse:
        """What a purchase date implies, before anything is written.

        The entry form prices a holding from the confirmation-day NAV, so the
        arithmetic has to run server-side where the NAV history lives; the
        figures here are the estimate alone and never include overrides the
        user typed into 手动修正.
        """
        settled = settlement_date(purchase_date, after_cutoff)
        latest = await fund_repository.get_latest_nav(fund_code)
        settled_row = await fund_repository.get_nav_on_or_before(fund_code, settled)
        unit_nav = latest.unit_nav if latest else None
        settled_nav = settled_row.unit_nav if settled_row else None
        figures = position_figures(market_value=market_value, unit_nav=unit_nav, settled_nav=settled_nav)
        return PositionPreviewResponse(
            fund_code=fund_code,
            purchase_date=purchase_date,
            purchase_after_cutoff=after_cutoff,
            settlement_date=settled,
            holding_days=max((business_today() - settled).days, 0),
            settled_nav=settled_nav,
            settled_nav_date=settled_row.nav_date if settled_row else None,
            unit_nav=unit_nav,
            nav_date=latest.nav_date if latest else None,
            shares=figures.shares,
            cost_amount=figures.cost_amount,
            average_cost_nav=figures.average_cost_nav,
            profit_loss=figures.profit_loss,
            profit_loss_rate=figures.profit_loss_rate,
        )

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
        # One batched read instead of a per-position NAV query.
        latest_navs = await fund_repository.get_latest_navs([position.fund_code for position in positions])
        settled_navs = await self._settled_navs(positions)

        for position in positions:
            summary.total_market_value += position.market_value or 0.0
            key = self._settlement_key(position)
            figures = position_figures(
                market_value=position.market_value,
                cost_amount=position.cost_amount,
                profit_loss=position.profit_loss,
                unit_nav=latest_navs[position.fund_code].unit_nav if position.fund_code in latest_navs else None,
                settled_nav=settled_navs.get(key) if key else None,
            )
            summary.total_cost += figures.cost_amount or 0.0
            summary.total_profit_loss += figures.profit_loss or 0.0
            latest = latest_navs.get(position.fund_code)
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

    @staticmethod
    async def _recent_history(fund_codes: list[str]) -> dict[str, list[FundNav]]:
        """NAV rows for the trailing windows, one batched query per call.

        Only a month-plus is read: the longest window shown is 本月收益, and
        pulling every historical row per position would dwarf the answer.
        """
        return await fund_repository.get_nav_history_map(
            fund_codes, start_date=business_today() - timedelta(days=_WINDOW_LOOKBACK_DAYS)
        )

    @staticmethod
    def _settlement_key(position: PortfolioPosition) -> tuple[str, date] | None:
        """(基金代码, 适用净值日) when the row says when it was bought."""
        if position.purchase_date is None:
            return None
        return position.fund_code, settlement_date(position.purchase_date, position.purchase_after_cutoff)

    async def _settled_navs(self, positions: list[PortfolioPosition]) -> dict[tuple[str, date], float]:
        """Confirmation-day NAVs for the rows that need a cost estimate.

        A snapshot that already carries 持仓成本 or 持有收益 can be answered
        without a price, so those are skipped. The remaining lookups run
        concurrently: each is an indexed single-row read, so the fan-out costs
        less than lining them up.
        """
        wanted: dict[tuple[str, date], None] = {}
        for position in positions:
            key = self._settlement_key(position)
            if (
                key is not None
                and key not in wanted
                and position.cost_amount is None
                and position.profit_loss is None
                and position.market_value is not None
            ):
                wanted[key] = None
        rows = await asyncio.gather(
            *(fund_repository.get_nav_on_or_before(fund_code, settled) for fund_code, settled in wanted)
        )
        return {key: row.unit_nav for key, row in zip(wanted, rows, strict=True) if row is not None and row.unit_nav}

    async def _position_item(
        self,
        position: PortfolioPosition,
        total_value: float,
        history: list[FundNav] | None = None,
        settled_navs: dict[tuple[str, date], float] | None = None,
    ) -> PositionItem:
        """Enrich a stored position with query-time derived metrics."""
        fund = await fund_repository.get_fund(position.fund_code)
        latest = await fund_repository.get_latest_nav(position.fund_code)

        unit_nav = latest.unit_nav if latest else None
        key = self._settlement_key(position)
        figures = position_figures(
            market_value=position.market_value,
            shares=position.shares,
            cost_amount=position.cost_amount,
            average_cost_nav=position.average_cost_nav,
            profit_loss=position.profit_loss,
            unit_nav=unit_nav,
            settled_nav=(settled_navs or {}).get(key) if key else None,
        )

        daily_profit_loss = None
        daily_return = latest.daily_return if latest else None
        if latest and latest.daily_return is not None and position.market_value:
            daily_profit_loss = latest.daily_return * position.market_value / 100.0

        weekly_profit_loss = monthly_profit_loss = None
        if latest is not None and history:
            points = [NavPoint(row.nav_date, row.unit_nav) for row in history if row.unit_nav is not None]
            weekly_profit_loss = period_profit_loss(
                position.market_value, window_return(points, latest.nav_date, _WEEKLY_DAYS)
            )
            monthly_profit_loss = period_profit_loss(position.market_value, period_return(points, latest.nav_date, 1))

        position_ratio = None
        if total_value > 0 and position.market_value is not None:
            position_ratio = position.market_value / total_value

        settled = holding_days = None
        if position.purchase_date is not None:
            settled = settlement_date(position.purchase_date, position.purchase_after_cutoff)
            holding_days = max((business_today() - settled).days, 0)

        return PositionItem(
            id=position.id,
            account_id=position.account_id,
            fund_code=position.fund_code,
            fund_name=fund.fund_name if fund else None,
            shares=figures.shares,
            cost_amount=figures.cost_amount,
            average_cost_nav=figures.average_cost_nav,
            market_value=position.market_value,
            profit_loss=figures.profit_loss,
            profit_loss_rate=figures.profit_loss_rate,
            # The entry form folds these back into 手动修正 only when the row
            # actually stores them; a derived figure must not look like a fact.
            cost_derived=figures.cost_derived,
            profit_derived=position.profit_loss is None and figures.profit_loss is not None,
            daily_profit_loss=daily_profit_loss,
            daily_return=daily_return,
            unit_nav=unit_nav,
            weekly_profit_loss=weekly_profit_loss,
            monthly_profit_loss=monthly_profit_loss,
            position_ratio=position_ratio,
            nav_date=latest.nav_date if latest else None,
            is_updated=latest is not None,
            purchase_date=position.purchase_date,
            purchase_after_cutoff=position.purchase_after_cutoff,
            settlement_date=settled,
            holding_days=holding_days,
            created_at=position.created_at,
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
