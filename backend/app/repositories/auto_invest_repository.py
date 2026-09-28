"""Data access for standing 定投 plans."""

from datetime import date

from sqlmodel import col, select

from app.core.database import get_async_session
from app.models.portfolio import AutoInvestPlan
from app.utils.clock import utc_now


class AutoInvestRepository:
    """Async data access for auto-invest plans."""

    async def list_plans(self, user_id: int, account_id: int | None = None) -> list[AutoInvestPlan]:
        """List the user's plans, optionally scoped to one account."""
        async with get_async_session() as session:
            statement = select(AutoInvestPlan).where(col(AutoInvestPlan.user_id) == user_id)
            if account_id is not None:
                statement = statement.where(col(AutoInvestPlan.account_id) == account_id)
            result = await session.execute(statement.order_by(col(AutoInvestPlan.start_date)))
            return list(result.scalars().all())

    async def get_plan(self, user_id: int, plan_id: int) -> AutoInvestPlan | None:
        """Load one plan owned by this user."""
        async with get_async_session() as session:
            result = await session.execute(
                select(AutoInvestPlan).where(col(AutoInvestPlan.id) == plan_id, col(AutoInvestPlan.user_id) == user_id)
            )
            return result.scalar_one_or_none()

    async def create_plan(
        self,
        user_id: int,
        account_id: int,
        fund_code: str,
        amount: float,
        frequency: str,
        run_day: int,
        start_date: date,
        end_date: date | None,
    ) -> AutoInvestPlan:
        """Add a plan; a fund may carry several with different schedules."""
        async with get_async_session() as session:
            plan = AutoInvestPlan(
                user_id=user_id,
                account_id=account_id,
                fund_code=fund_code,
                amount=amount,
                frequency=frequency,
                run_day=run_day,
                start_date=start_date,
                end_date=end_date,
            )
            session.add(plan)
            await session.flush()
            await session.refresh(plan)
            return plan

    async def update_plan(
        self,
        user_id: int,
        plan_id: int,
        amount: float | None = None,
        frequency: str | None = None,
        run_day: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        active: bool | None = None,
    ) -> AutoInvestPlan | None:
        """Patch the schedule. A None field means "not supplied" (spec 3.7.1)."""
        async with get_async_session() as session:
            plan = (
                await session.execute(
                    select(AutoInvestPlan).where(
                        col(AutoInvestPlan.id) == plan_id, col(AutoInvestPlan.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if plan is None:
                return None
            for key, value in {
                "amount": amount,
                "frequency": frequency,
                "run_day": run_day,
                "start_date": start_date,
                "end_date": end_date,
                "active": active,
            }.items():
                if value is not None:
                    setattr(plan, key, value)
            plan.updated_at = utc_now()
            session.add(plan)
            await session.flush()
            await session.refresh(plan)
            return plan

    async def mark_run(self, plan_id: int, scheduled_day: date) -> None:
        """Record how far the plan has been settled, so catching up is idempotent."""
        async with get_async_session() as session:
            plan = (
                await session.execute(select(AutoInvestPlan).where(col(AutoInvestPlan.id) == plan_id))
            ).scalar_one_or_none()
            if plan is not None and (plan.last_run_date is None or scheduled_day > plan.last_run_date):
                plan.last_run_date = scheduled_day
                plan.updated_at = utc_now()
                session.add(plan)

    async def delete_plan(self, user_id: int, plan_id: int) -> bool:
        """Remove one plan row. Its installments are the caller's to decide on."""
        async with get_async_session() as session:
            plan = (
                await session.execute(
                    select(AutoInvestPlan).where(
                        col(AutoInvestPlan.id) == plan_id, col(AutoInvestPlan.user_id) == user_id
                    )
                )
            ).scalar_one_or_none()
            if plan is None:
                return False
            await session.delete(plan)
            return True


auto_invest_repository = AutoInvestRepository()
