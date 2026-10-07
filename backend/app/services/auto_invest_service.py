"""定投计划：周期声明一次，之后把已经到期的各期结算出来.

真正扣钱的是平台，所以计划是用户自己的声明，不是这个应用观察到的事实。
结算写的是普通的买入流水，按每个扣款日当天的净值定价，
这样持仓的流水账本仍然是 份额 和 成本 的唯一来源 ——
也避免了用户在平台那边暂停计划之后，这边的数据悄悄错下去，
因为是他自己来改这条计划。
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

# 表单往前找下一个扣款日时，最多看这么远。
_LOOKAHEAD_DAYS = 120
_WEEK_DAYS = 7


class PlanInputError(Exception):
    """周期设置自相矛盾，例如 每周 却给了一个"每月几号"的扣款日."""


class PlanNotFoundError(Exception):
    """计划不存在，或者属于其他用户."""


class AutoInvestService:
    """定期定额买入计划的异步操作."""

    async def list_plans(self, user_id: int, account_id: int | None = None) -> tuple[list[AutoInvestPlanItem], int]:
        """返回全部计划，并且先把它们结算到今天.

        读取这个动作本身就负责结算：worker 不一定一直在跑，
        只靠定时任务结算的计划，
        在没人启动它的机器上会悄悄落后于日期。
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
        """校验过账户归属、以及周期本身是否自洽之后，新增一条计划."""
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
        """修改周期。已经写出去的各期流水不动."""
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
        """删除计划，可以顺带删掉它写下的每一期流水.

        只删计划的话，它买出来的流水还留在账本里 —— 那是真花出去的钱。
        ``with_orders`` 是给误建计划准备的撤销路径：
        删掉那些流水，再把持仓重新投影一遍。
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
        """把计划欠下的各期流水，按时间从早到晚全部写出来."""
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
                # 基金净值要收盘之后才公布，所以今天这期还算不出价格；
                # 下一次读取时会重新结算到它。
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
        """拒绝无法唯一解读的周期设置.

        Raises:
            PlanInputError: 周定投给了 1-7 之外的星期，
                或者结束日期早于开始日期。每天 本来就不需要指定哪一天。
        """
        if frequency not in ("daily", "monthly") and run_day > _WEEK_DAYS:
            raise PlanInputError(f"{frequency} 定投的扣款日要在 1-7 之间（周一到周日）")
        if end_date is not None and end_date < start_date:
            raise PlanInputError("结束日期不能早于开始日期")

    async def _item(self, plan: AutoInvestPlan) -> AutoInvestPlanItem:
        """把计划映射成响应，并算出下一个扣款日."""
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
        """今天之后的下一个应付日；计划已经走完时返回 None."""
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
