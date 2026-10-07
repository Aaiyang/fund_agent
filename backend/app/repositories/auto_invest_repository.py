"""定投计划的数据访问."""

from datetime import date

from sqlmodel import col, select

from app.core.database import get_async_session
from app.models.portfolio import AutoInvestPlan
from app.utils.clock import utc_now


class AutoInvestRepository:
    """定投计划的异步数据访问."""

    async def list_plans(self, user_id: int, account_id: int | None = None) -> list[AutoInvestPlan]:
        """列出该用户的定投计划，可用 account_id 收窄到一个账户."""
        async with get_async_session() as session:
            statement = select(AutoInvestPlan).where(col(AutoInvestPlan.user_id) == user_id)
            if account_id is not None:
                statement = statement.where(col(AutoInvestPlan.account_id) == account_id)
            result = await session.execute(statement.order_by(col(AutoInvestPlan.start_date)))
            return list(result.scalars().all())

    async def get_plan(self, user_id: int, plan_id: int) -> AutoInvestPlan | None:
        """读取一条属于该用户的计划."""
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
        """新增一条计划；同一只基金可以挂多条不同节奏的计划."""
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
        """修改计划的排期。某个字段为 None 表示调用方没给它（spec 3.7.1）."""
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
        """记下计划已经结算到哪一天，补跑因此是幂等的."""
        async with get_async_session() as session:
            plan = (
                await session.execute(select(AutoInvestPlan).where(col(AutoInvestPlan.id) == plan_id))
            ).scalar_one_or_none()
            if plan is not None and (plan.last_run_date is None or scheduled_day > plan.last_run_date):
                plan.last_run_date = scheduled_day
                plan.updated_at = utc_now()
                session.add(plan)

    async def delete_plan(self, user_id: int, plan_id: int) -> bool:
        """删掉一条计划记录。它已生成的期次由调用方决定怎么处理."""
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

    async def delete_plans_for_fund(self, user_id: int, account_id: int, fund_code: str) -> int:
        """删掉某账户下指向这只基金的全部计划，返回删掉的条数.

        计划如果活得比它买入的基金还久，下一期结算时就会把用户刚删掉的持仓重新写
        回来，所以两者要一起删。
        """
        async with get_async_session() as session:
            plans = (
                (
                    await session.execute(
                        select(AutoInvestPlan).where(
                            col(AutoInvestPlan.user_id) == user_id,
                            col(AutoInvestPlan.account_id) == account_id,
                            col(AutoInvestPlan.fund_code) == fund_code,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for plan in plans:
                await session.delete(plan)
            return len(plans)


auto_invest_repository = AutoInvestRepository()
