"""Portfolio domain service: accounts, positions, summary, transactions.

Derived metrics (rates, daily P/L, position ratio) are computed at query time
from stored snapshots + latest NAVs — never persisted, so they can't drift
(MVP spec 12.8). All future agents/tools must go through this service.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.analytics import period_return, window_return
from app.analytics.positions import (
    Direction,
    LedgerRow,
    Operation,
    OrderDelta,
    price_buy,
    price_sell,
    position_figures,
    project_ledger,
)
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
    TradeLeg,
    TradePreviewResponse,
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


class NavNotPublishedError(Exception):
    """The confirm day has no NAV yet, so an order cannot become shares."""

    def __init__(self, fund_code: str, confirm_date: date) -> None:
        """Carry both halves of the answer so the form can explain the wait."""
        super().__init__(f"{fund_code} has no published NAV at or before {confirm_date}")
        self.fund_code = fund_code
        self.confirm_date = confirm_date


class TradeInputError(Exception):
    """The order is missing the figure its direction needs."""


class TradeTooLargeError(Exception):
    """Selling more shares than the ledger holds would drive it negative."""

    def __init__(self, held: float) -> None:
        """Keep the current holding so the route can say how much is sellable."""
        super().__init__(f"only {held} shares held")
        self.held = held


@dataclass(frozen=True)
class _PricedOrder:
    """The session an order was priced against, with the NAV that did it."""

    confirm_date: date
    nav: float
    nav_date: date


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
        ledger = await portfolio_repository.ledger_rows(user_id, account_id)
        items = []
        for position in positions:
            items.append(await self._position_item(position, total_value, histories.get(position.fund_code), ledger))
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
        ledger = await portfolio_repository.ledger_rows(user_id, account_id)
        return await self._position_item(position, total_value, histories.get(fund_code), ledger)

    async def upsert_position(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        expected_version: int | None = None,
        purchase_date: date | None = None,
        reset: Sequence[str] = (),
        **fields: float | None,
    ) -> PositionItem:
        """Create or update a position snapshot with optimistic locking.

        A fund with a BUY/SELL ledger only accepts 持有金额 and 首次购买日期 from
        here: 份额 and 持仓成本 belong to the ledger, and letting a snapshot
        overwrite them would silently undo recorded trades.

        Without a ledger the form states one pair — 金额 with 收益, or 份额 with
        持仓成本价 — and the other money figures follow from it. Restating either
        pair retires the stored figures it replaces, so an import's old cost and
        a newly typed profit cannot both claim to be right.

        Raises:
            AccountNotFoundError: unknown or foreign account → HTTP 404.
            PositionConflictError: version mismatch → HTTP 409 upstream.
        """
        await self.ensure_account(user_id, account_id)
        ledger = await portfolio_repository.ledger_rows(user_id, account_id)
        if ledger.get((account_id, fund_code)):
            for owned in ("cost_amount", "profit_loss"):
                fields.pop(owned, None)
                reset = [name for name in reset if name != owned]
        elif fields.get("average_cost_nav") is not None:
            reset = [*reset, "cost_amount", "profit_loss"]
        elif fields.get("profit_loss") is not None:
            reset = [*reset, "cost_amount", "average_cost_nav"]
        updated = await portfolio_repository.upsert_position(
            user_id,
            account_id,
            fund_code,
            expected_version,
            purchase_date=purchase_date,
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
        ledger = await portfolio_repository.ledger_rows(user_id, account_id)
        return await self._position_item(updated, total_value, histories.get(fund_code), ledger)

    @staticmethod
    async def _price_order(fund_code: str, trade_date: date, after_cutoff: bool) -> _PricedOrder:
        """Resolve which session an order was priced against, and its NAV.

        Raises:
            NavNotPublishedError: the fund has no NAV at or before the confirm
                day, so the order cannot be turned into shares yet.
        """
        confirm = settlement_date(trade_date, after_cutoff)
        row = await fund_repository.get_nav_on_or_before(fund_code, confirm)
        if row is None or not row.unit_nav:
            raise NavNotPublishedError(fund_code, confirm)
        return _PricedOrder(confirm_date=confirm, nav=row.unit_nav, nav_date=row.nav_date)

    @staticmethod
    def _opening_row(position: PortfolioPosition | None, unit_nav: float | None) -> LedgerRow | None:
        """The snapshot a ledger has to start from, when there was one first.

        Recording a purchase on a fund that arrived as a holdings screenshot
        used to reset its basis to that single order: the snapshot said 1019.19
        and the ledger said 1000. Carrying the snapshot in as an opening row
        makes the new order an addition to what he already held.

        The seed is built from the *resolved* figures, not the stored columns:
        a 按金额 snapshot keeps only 市值 and 收益, so its units and cost exist
        nowhere until they are worked out. Reading the columns directly made
        such a holding seed an opening of nothing, and the first 加仓 or 定投
        then looked like it had cleared the position outright.
        """
        if position is None:
            return None
        figures = position_figures(
            market_value=position.market_value,
            shares=position.shares,
            cost_amount=position.cost_amount,
            average_cost_nav=position.average_cost_nav,
            profit_loss=position.profit_loss,
            unit_nav=unit_nav,
        )
        if not figures.shares:
            return None
        # A row with units but no cost and no profit has no basis to carry.
        # Break-even is the only reading that does not invent a gain or a loss.
        cost = figures.cost_amount if figures.cost_amount is not None else position.market_value
        if cost is None:
            return None
        return LedgerRow(kind="BUY", shares=figures.shares, amount=cost)

    def _projection_rows(
        self, position: PortfolioPosition | None, rows: list[LedgerRow], unit_nav: float | None
    ) -> list[LedgerRow]:
        """Rows the holding is projected from, opening balance included.

        Both the preview and the write run through here, so the numbers shown
        before saving are the numbers saving produces.
        """
        if rows:
            return rows
        opening = self._opening_row(position, unit_nav)
        return [opening] if opening else []

    @staticmethod
    async def _rows_of(user_id: int, account_id: int, fund_code: str) -> list[LedgerRow]:
        """The ledger one fund's holding is projected from."""
        return (await portfolio_repository.ledger_rows(user_id, account_id)).get((account_id, fund_code), [])

    @staticmethod
    async def _unit_nav(fund_code: str) -> float | None:
        """The price the snapshot's 市值 is marked at, for the opening seed."""
        latest = await fund_repository.get_latest_nav(fund_code)
        return latest.unit_nav if latest and latest.unit_nav else None

    async def _planned_rows(
        self, user_id: int, account_id: int, fund_code: str
    ) -> tuple[PortfolioPosition | None, list[LedgerRow]]:
        """A fund's stored snapshot and its ledger, read together for pricing."""
        position = await portfolio_repository.get_position(user_id, account_id, fund_code)
        rows = await self._rows_of(user_id, account_id, fund_code)
        return position, self._projection_rows(position, rows, await self._unit_nav(fund_code))

    async def _ensure_opening(self, user_id: int, account_id: int, fund_code: str, confirm: date) -> None:
        """Carry a snapshot holding into the ledger before the first row lands on it.

        This is the write side of ``_projection_rows``: whatever the preview
        priced against is what gets persisted, so the two can never disagree
        about whether the old holding survived the new order.
        """
        if await self._rows_of(user_id, account_id, fund_code):
            return
        position = await portfolio_repository.get_position(user_id, account_id, fund_code)
        opening = self._opening_row(position, await self._unit_nav(fund_code))
        if opening is None or position is None:
            return
        await portfolio_repository.add_transaction(
            user_id=user_id,
            account_id=account_id,
            fund_code=fund_code,
            transaction_type="OPENING",
            trade_date=position.purchase_date or confirm,
            confirm_date=position.purchase_date,
            shares=opening.shares,
            amount=opening.amount,
            source="position_snapshot",
        )

    async def reproject(self, user_id: int, account_id: int, fund_code: str) -> None:
        """Rebuild a holding from its ledger. Public for the plan undo path."""
        await self._reproject(user_id, account_id, fund_code)

    async def _reproject(self, user_id: int, account_id: int, fund_code: str) -> None:
        """Re-materialise a position's shares, cost and value from its ledger.

        Recomputed from every row rather than nudged by a delta, so a fund
        always reads back the same way no matter what order rows arrived in.
        """
        rows = await self._rows_of(user_id, account_id, fund_code)
        if not rows:
            return
        totals = project_ledger(rows)
        latest = await fund_repository.get_latest_nav(fund_code)
        await portfolio_repository.upsert_position(
            user_id,
            account_id,
            fund_code,
            None,
            shares=totals.shares,
            cost_amount=totals.cost_amount,
            market_value=totals.shares * latest.unit_nav if latest and latest.unit_nav else None,
            purchase_date=await portfolio_repository.earliest_confirm_date(user_id, account_id, fund_code),
            # Whatever a snapshot left in these two columns describes the old
            # holding, not the one this ledger now adds up to.
            reset=["average_cost_nav", "profit_loss"],
        )

    @staticmethod
    def _leg(
        fund_code: str, priced: _PricedOrder, rows: list[LedgerRow], delta: OrderDelta, direction: Direction
    ) -> TradeLeg:
        """One fund's before/after, with the new row folded in."""
        before = project_ledger(rows)
        after = project_ledger([*rows, LedgerRow(kind=direction, shares=delta.shares, amount=delta.amount)])
        return TradeLeg(
            fund_code=fund_code,
            direction=direction,
            confirm_nav=priced.nav,
            confirm_nav_date=priced.nav_date,
            shares_delta=delta.shares if direction == "BUY" else -delta.shares,
            amount=delta.amount,
            shares_before=before.shares,
            cost_before=before.cost_amount,
            shares_after=after.shares,
            cost_after=after.cost_amount,
        )

    async def _plan_order(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        operation: Operation,
        trade_date: date,
        after_cutoff: bool,
        amount: float | None,
        shares: float | None,
        target_code: str | None,
    ) -> tuple[date, list[TradeLeg], list[tuple[str, str, OrderDelta, float]]]:
        """Price an order into the ledger rows it would write.

        The preview and the write both run through here, so the numbers shown
        before saving are exactly the numbers saving produces.

        Raises:
            NavNotPublishedError: either fund has no NAV for the confirm day.
            TradeTooLargeError: the exit sells more than the holding carries.
        """
        priced = await self._price_order(fund_code, trade_date, after_cutoff)
        _, source_rows = await self._planned_rows(user_id, account_id, fund_code)
        held = project_ledger(source_rows).shares

        if operation == "CONVERT":
            target = str(target_code)
            if target == fund_code:
                raise TradeInputError("转换目标不能是同一只基金")
            target_priced = await self._price_order(target, trade_date, after_cutoff)
            out = price_sell(priced.nav, float(shares or 0.0))
            if out.shares > held:
                raise TradeTooLargeError(held)
            into = price_buy(target_priced.nav, out.amount)
            _, target_rows = await self._planned_rows(user_id, account_id, target)
            legs = [
                self._leg(fund_code, priced, source_rows, out, "SELL"),
                self._leg(target, target_priced, target_rows, into, "BUY"),
            ]
            rows = [
                (fund_code, "CONVERT_OUT", out, priced.nav),
                (target, "CONVERT_IN", into, target_priced.nav),
            ]
            return priced.confirm_date, legs, rows

        direction: Direction = "SELL" if operation == "SELL" else "BUY"
        delta = self._order_delta(direction, priced.nav, amount, shares)
        if direction == "SELL" and delta.shares > held:
            raise TradeTooLargeError(held)
        row_type = {"BUY": "BUY", "SELL": "SELL", "AUTO_INVEST": "AUTO_INVEST"}[operation]
        legs = [self._leg(fund_code, priced, source_rows, delta, direction)]
        return priced.confirm_date, legs, [(fund_code, row_type, delta, priced.nav)]

    async def preview_trade(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        operation: Operation,
        trade_date: date,
        after_cutoff: bool,
        amount: float | None = None,
        shares: float | None = None,
        target_code: str | None = None,
    ) -> TradePreviewResponse:
        """What this order would do to the holding, before writing anything."""
        await self.ensure_account(user_id, account_id)
        confirm, legs, _ = await self._plan_order(
            user_id, account_id, fund_code, operation, trade_date, after_cutoff, amount, shares, target_code
        )
        return TradePreviewResponse(
            operation=operation,
            trade_date=trade_date,
            after_cutoff=after_cutoff,
            confirm_date=confirm,
            legs=legs,
        )

    async def record_trade(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        operation: Operation,
        trade_date: date,
        after_cutoff: bool,
        amount: float | None = None,
        shares: float | None = None,
        target_code: str | None = None,
        source: str = "manual",
        external_ref: str | None = None,
    ) -> PositionItem:
        """Write an order's ledger rows and re-project every fund it touched."""
        await self.ensure_account(user_id, account_id)
        confirm, _, rows = await self._plan_order(
            user_id, account_id, fund_code, operation, trade_date, after_cutoff, amount, shares, target_code
        )
        touched: list[str] = []
        for index, (fund, row_type, delta, nav) in enumerate(rows):
            await self._ensure_opening(user_id, account_id, fund, confirm)
            await portfolio_repository.add_transaction(
                user_id=user_id,
                account_id=account_id,
                fund_code=fund,
                transaction_type=row_type,
                trade_date=trade_date,
                confirm_date=confirm,
                shares=delta.shares,
                nav=nav,
                amount=delta.amount,
                source=source,
                # Only the buying leg carries the idempotency key: one key per
                # order, and a retry must not add the pair twice.
                external_transaction_id=external_ref if index == 0 else None,
            )
            if fund not in touched:
                touched.append(fund)
        for fund in touched:
            await self._reproject(user_id, account_id, fund)
        logger.info(
            "trade_recorded",
            user_id=user_id,
            account_id=account_id,
            fund_code=fund_code,
            operation=operation,
            confirm_date=confirm.isoformat(),
            rows=len(rows),
            source=source,
        )
        position = await self.get_position(user_id, account_id, fund_code)
        if position is None:  # the account and position both exist by now
            raise AssertionError(f"position vanished after trade on {fund_code}")
        return position

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
        ledger = await portfolio_repository.ledger_rows(user_id, account_id)

        for position in positions:
            summary.total_market_value += position.market_value or 0.0
            rows = ledger.get((position.account_id, position.fund_code), [])
            totals = project_ledger(rows) if rows else None
            figures = position_figures(
                market_value=position.market_value,
                cost_amount=totals.cost_amount if totals else position.cost_amount,
                profit_loss=None if totals else position.profit_loss,
                unit_nav=latest_navs[position.fund_code].unit_nav if position.fund_code in latest_navs else None,
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
                    confirm_date=record.confirm_date,
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
    def _order_delta(direction: Direction, nav: float, amount: float | None, shares: float | None) -> OrderDelta:
        """Turn the figure the user gave into ledger units at this day's NAV.

        Raises:
            TradeInputError: 买入 without an amount or 卖出 without a share
                count. Neither can be guessed — one buys an unknown quantity,
                the other sells an unknown part of the holding.
        """
        if direction == "BUY":
            if not amount:
                raise TradeInputError("买入需要填写金额")
            return price_buy(nav, amount)
        if not shares:
            raise TradeInputError("卖出需要填写份额")
        return price_sell(nav, shares)

    async def _position_item(
        self,
        position: PortfolioPosition,
        total_value: float,
        history: list[FundNav] | None = None,
        ledger: dict[tuple[int, str], list[LedgerRow]] | None = None,
    ) -> PositionItem:
        """Enrich a stored position with query-time derived metrics."""
        fund = await fund_repository.get_fund(position.fund_code)
        latest = await fund_repository.get_latest_nav(position.fund_code)

        unit_nav = latest.unit_nav if latest else None
        rows = (ledger or {}).get((position.account_id, position.fund_code), [])
        totals = project_ledger(rows) if rows else None
        figures = position_figures(
            market_value=position.market_value,
            shares=totals.shares if totals else position.shares,
            cost_amount=totals.cost_amount if totals else position.cost_amount,
            # With a ledger these two describe a holding that no longer exists.
            average_cost_nav=None if totals else position.average_cost_nav,
            profit_loss=None if totals else position.profit_loss,
            unit_nav=unit_nav,
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

        # 首次购买确认日 is maintained by the ledger; without one it is whatever
        # the snapshot recorded, and 持有天数 counts from it directly.
        holding_days = max((business_today() - position.purchase_date).days, 0) if position.purchase_date else None

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
            # The entry form keeps these off its inputs when set: a figure the
            # row does not actually store must not look like a fact.
            shares_derived=figures.shares_derived,
            cost_derived=figures.cost_derived,
            average_cost_nav_derived=figures.average_cost_nav_derived,
            profit_derived=figures.profit_derived,
            daily_profit_loss=daily_profit_loss,
            daily_return=daily_return,
            unit_nav=unit_nav,
            weekly_profit_loss=weekly_profit_loss,
            monthly_profit_loss=monthly_profit_loss,
            position_ratio=position_ratio,
            nav_date=latest.nav_date if latest else None,
            is_updated=latest is not None,
            purchase_date=position.purchase_date,
            holding_days=holding_days,
            trade_count=len(rows),
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
