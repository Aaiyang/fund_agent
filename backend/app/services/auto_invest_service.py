"""定投计划: state the schedule once, then settle whatever has come due.

The platform is what actually debits the money, so a plan is the user's own
declaration rather than something this app observes. Settling writes ordinary
purchase rows priced on each due day's NAV, which keeps the holding's ledger
the single source for 份额 and 成本 — and keeps a plan the user paused at the
platform from being silently wrong here, because he edits the plan.
"""

from datetime import date, timedelta

from app.analytics.schedule import Frequency, due_days
from app.core.logging import logger
from app.models.portfolio import AutoInvestPlan
from app.repositories.auto_invest_repository import auto_invest_repository
from app.repositories.fund_repository import fund_repository
from app.repositories.portfolio_repository import portfolio_repository
from app.schemas.auto_invest import AutoInvestPlanItem
from app.services.portfolio_service import (
    NavNotPublishedError,
    TradeInputError,
    portfolio_service,
)
from app.utils.clock import business_today

# How far ahead the form looks for the next debit day.
_LOOKAHEAD_DAYS = 120
_WEEK_DAYS = 7


class PlanInputError(Exception):
    """The schedule contradicts itself, e.g. 每周 with a day-of-month."""


class PlanNotFoundError(Exception):
    """The plan does not exist or belongs to another user."""


class AutoInvestService:
    """Async operations for standing purchase plans."""

    async def list_plans(self, user_id: int, account_id: int | None = None) -> tuple[list[AutoInvestPlanItem], int]:
        """Every plan, caught up to today first.

        Reading is what settles a plan: the worker is not always running, and a
        plan that is only ever settled by a schedule would silently fall behind
        on a machine where nobody started it.
        """
        plans = await auto_invest_repository.list_plans(user_id, account_id)
        settled = 0
        for plan in plans:
            settled += await self._settle(plan)
        if settled:
            plans = await auto_invest_repository.list_plans(user_id, account_id)
        items = [await self._item(plan) for plan in plans]
        return items, settled

    async def create_plan(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        amount: float,
        frequency: Frequency,
        run_day: int,
        start_date: date,
        end_date: date | None,
    ) -> AutoInvestPlanItem:
        """Add a plan after checking the account and the schedule's own shape."""
        await portfolio_service.ensure_account(user_id, account_id)
        self._check(frequency, run_day, start_date, end_date)
        plan = await auto_invest_repository.create_plan(
            user_id, account_id, fund_code, amount, frequency, run_day, start_date, end_date
        )
        logger.info(
            "auto_invest_plan_created",
            user_id=user_id,
            plan_id=plan.id,
            fund_code=fund_code,
            frequency=frequency,
            run_day=run_day,
        )
        return await self._item(plan)

    async def update_plan(
        self,
        user_id: int,
        plan_id: int,
        amount: float | None = None,
        frequency: Frequency | None = None,
        run_day: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        active: bool | None = None,
    ) -> AutoInvestPlanItem:
        """Change the schedule. Installments already written are left alone."""
        current = await auto_invest_repository.get_plan(user_id, plan_id)
        if current is None:
            raise PlanNotFoundError(f"auto invest plan {plan_id} not found")
        self._check(
            frequency or current.frequency,  # pyright: ignore[reportArgumentType]
            run_day or current.run_day,
            start_date or current.start_date,
            end_date if end_date is not None else current.end_date,
        )
        updated = await auto_invest_repository.update_plan(
            user_id, plan_id, amount, frequency, run_day, start_date, end_date, active
        )
        if updated is None:
            raise PlanNotFoundError(f"auto invest plan {plan_id} not found")
        return await self._item(updated)

    async def delete_plan(self, user_id: int, plan_id: int, with_orders: bool = False) -> bool:
        """Remove a plan, and optionally every installment it wrote.

        Deleting the plan alone leaves its purchases in the ledger — they are
        money that really moved. ``with_orders`` is the undo path for a plan
        created by mistake: it drops those rows and re-projects the holding.
        """
        current = await auto_invest_repository.get_plan(user_id, plan_id)
        if current is None:
            return False
        deleted = await auto_invest_repository.delete_plan(user_id, plan_id)
        if deleted and with_orders:
            removed = await portfolio_repository.delete_transactions_by_source(user_id, f"auto_invest:{plan_id}")
            await portfolio_service.reproject(user_id, current.account_id, current.fund_code)
            logger.info(
                "auto_invest_plan_deleted_with_orders",
                user_id=user_id,
                plan_id=plan_id,
                orders_removed=removed,
            )
        return deleted

    async def _settle(self, plan: AutoInvestPlan) -> int:
        """Write every installment the plan is due for, oldest first."""
        if not plan.active:
            return 0
        days = due_days(
            plan.frequency,  # pyright: ignore[reportArgumentType]
            plan.run_day,
            plan.start_date,
            plan.end_date,
            plan.last_run_date,
            business_today(),
        )
        written = 0
        for day in days:
            reference = f"plan:{plan.id}:{day.isoformat()}"
            if await portfolio_repository.has_transaction_ref(plan.user_id, reference):
                await auto_invest_repository.mark_run(plan.id or 0, day)
                continue
            try:
                await portfolio_service.record_trade(
                    plan.user_id,
                    plan.account_id,
                    plan.fund_code,
                    "AUTO_INVEST",
                    day,
                    False,
                    amount=plan.amount,
                    source=f"auto_invest:{plan.id}",
                    external_ref=reference,
                )
            except (NavNotPublishedError, TradeInputError) as error:
                # A fund NAV publishes after the close, so today's debit simply
                # is not priceable yet; the next read picks it up again.
                logger.info(
                    "auto_invest_installment_deferred",
                    plan_id=plan.id,
                    scheduled_date=day.isoformat(),
                    reason=str(error),
                )
                break
            await auto_invest_repository.mark_run(plan.id or 0, day)
            written += 1
        if written:
            logger.info("auto_invest_installments_written", plan_id=plan.id, count=written)
        return written

    @staticmethod
    def _check(frequency: Frequency, run_day: int, start_date: date, end_date: date | None) -> None:
        """Reject a schedule that cannot be read unambiguously.

        Raises:
            PlanInputError: a weekday outside 1-7 on a weekly plan, or an end
                date before the plan starts.
        """
        if frequency != "monthly" and run_day > _WEEK_DAYS:
            raise PlanInputError(f"{frequency} 定投的扣款日要在 1-7 之间（周一到周日）")
        if end_date is not None and end_date < start_date:
            raise PlanInputError("结束日期不能早于开始日期")

    async def _item(self, plan: AutoInvestPlan) -> AutoInvestPlanItem:
        """Map a plan to its response, with the next debit day worked out."""
        fund = await fund_repository.get_fund(plan.fund_code)
        return AutoInvestPlanItem(
            id=plan.id or 0,
            account_id=plan.account_id,
            fund_code=plan.fund_code,
            fund_name=fund.fund_name if fund else None,
            amount=plan.amount,
            frequency=plan.frequency,  # pyright: ignore[reportArgumentType]
            run_day=plan.run_day,
            start_date=plan.start_date,
            end_date=plan.end_date,
            active=plan.active,
            last_run_date=plan.last_run_date,
            next_due=self._next_due(plan),
        )

    @staticmethod
    def _next_due(plan: AutoInvestPlan) -> date | None:
        """The next scheduled day after today, or None once the plan is done."""
        if not plan.active:
            return None
        today = business_today()
        since = max(today, plan.last_run_date or today - timedelta(days=1))
        upcoming = due_days(
            plan.frequency,  # pyright: ignore[reportArgumentType]
            plan.run_day,
            plan.start_date,
            plan.end_date,
            since,
            today + timedelta(days=_LOOKAHEAD_DAYS),
        )
        return upcoming[0] if upcoming else None


auto_invest_service = AutoInvestService()
