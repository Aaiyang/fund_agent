"""组合域服务：账户、持仓、汇总、流水.

派生指标（收益率、当日收益、持仓占比）在查询时用「已落库的快照 + 最新净值」算出来，
从不落库，所以不会出现口径漂移（MVP spec 12.8）。
后续所有 agent/工具都必须经过这个服务。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json

from sqlalchemy.exc import IntegrityError

from app.analytics import disclosed_change, period_return, window_return
from app.analytics.allocation import position_weight
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
from app.core.database import transaction_scope
from app.models.fund import FundNav
from app.models.portfolio import PortfolioAccount, PortfolioPosition
from app.repositories.auto_invest_repository import auto_invest_repository
from app.repositories.fund_repository import fund_repository
from app.repositories.portfolio_repository import portfolio_repository
from app.schemas.portfolio import (
    AccountItem,
    PortfolioSummary,
    PortfolioResearchSnapshot,
    PositionItem,
    TradeLeg,
    TradePreviewResponse,
    TransactionItem,
)
from app.utils.clock import business_today, utc_now
from app.utils.market_quote_policy import finite_number


class PositionConflictError(Exception):
    """乐观锁失败 —— 另一个写入方抢先更新了这条持仓."""


class AccountNotFoundError(Exception):
    """账户不存在，或者属于别的用户（spec 16 的用户隔离）."""


class AccountNameConflictError(Exception):
    """该用户名下已经有别的账户用了这个名字."""

    def __init__(self, name: str) -> None:
        """把冲突的名字带出来，路由才能原样回显给用户."""
        super().__init__(name)
        self.name = name


class NavNotPublishedError(Exception):
    """确认日还没有公布净值，所以这笔委托还换不成份额."""

    def __init__(self, fund_code: str, confirm_date: date) -> None:
        """基金代码和确认日一起带上，表单才能说清要等到什么时候."""
        super().__init__(f"{fund_code} has no published NAV at or before {confirm_date}")
        self.fund_code = fund_code
        self.confirm_date = confirm_date


class TradeInputError(Exception):
    """这笔委托缺少它的方向所必需的那个数值."""


class TradeIdempotencyConflictError(Exception):
    """同一请求键已被另一组交易参数使用."""


class TradeTooLargeError(Exception):
    """卖出的份额比流水账本里持有的还多，会把账本写成负数."""

    def __init__(self, held: float) -> None:
        """带上当前持有份额，路由才能告诉用户最多能卖多少."""
        super().__init__(f"only {held} shares held")
        self.held = held


@dataclass(frozen=True)
class _PricedOrder:
    """一笔委托定价时对应的那个确认时段，以及给它定价的净值."""

    confirm_date: date
    nav: float
    nav_date: date


_WEEKLY_DAYS = 7
_WINDOW_LOOKBACK_DAYS = 45


def period_profit_loss(market_value: float | None, fraction: float | None) -> float | None:
    """一个区间里赚到的钱，口径与 昨日收益 保持一致.

    当日收益那一列是用*当前*持有金额乘以收益率，而不是用区间起点的金额；
    周收益/月收益/当日收益统一按这一个口径算，
    才不会因四舍五入出现几个厘的差额。
    """
    if market_value is None or fraction is None:
        return None
    return market_value * fraction


class PortfolioService:
    """异步的资产组合操作."""

    # ------------------------------------------------------------------
    # 账户
    # ------------------------------------------------------------------

    async def ensure_account(self, user_id: int, account_id: int, *, for_update: bool = False) -> PortfolioAccount:
        """返回该账户；账户不属于调用方时抛异常.

        所有按账户范围的写入、以及显式指定账户的读取都走这里；持仓和流水是以
        account_id 为键的，仓储层分不清"账户是别人的"和"账户下本来就是空的"，
        所以归属必须在这一层先查清楚。
        """
        account = await portfolio_repository.get_account(user_id, account_id, for_update=for_update)
        if account is None:
            raise AccountNotFoundError(f"portfolio account {account_id} not found")
        return account

    async def list_accounts(self, user_id: int) -> list[AccountItem]:
        """列出账户，附带导入状态."""
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
        """创建账户；同一个用户名下账户名唯一."""
        if await portfolio_repository.find_account_by_name(user_id, name) is not None:
            raise AccountNameConflictError(name)
        try:
            account = await portfolio_repository.create_account(user_id, name, source_app, account_type, import_mode)
        except IntegrityError as error:
            # 只有并发创建才能绕过上面这次重名检查。
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
        """给账户改名 / 换来源标签."""
        if name is not None and await portfolio_repository.find_account_by_name(user_id, name, exclude_id=account_id):
            raise AccountNameConflictError(name)
        try:
            account = await portfolio_repository.update_account(user_id, account_id, name, source_app)
        except IntegrityError as error:
            raise AccountNameConflictError(name or "") from error
        return self._account_item(account) if account else None

    async def delete_account(self, user_id: int, account_id: int) -> bool:
        """删除账户，以及它名下一切数据."""
        deleted = await portfolio_repository.delete_account(user_id, account_id)
        logger.info("portfolio_account_deleted", user_id=user_id, account_id=account_id, deleted=deleted)
        return deleted

    # ------------------------------------------------------------------
    # 持仓
    # ------------------------------------------------------------------

    async def list_positions(self, user_id: int, account_id: int | None = None) -> list[PositionItem]:
        """列出持仓，含派生指标与基金名称."""
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

    async def research_snapshot(self, user_id: int, account_id: int | None = None) -> PortfolioResearchSnapshot:
        """批量生成轻量研究快照，复用账本投影，不加载周/月历史或截断计算行."""
        if account_id is not None:
            await self.ensure_account(user_id, account_id)
        positions = await portfolio_repository.list_positions(user_id, account_id)
        codes = list(dict.fromkeys(row.fund_code for row in positions))
        funds = await fund_repository.get_funds(codes)
        navs = await fund_repository.get_latest_navs(codes)
        ledger = await portfolio_repository.ledger_rows(user_id, account_id)
        total = sum(finite_number(row.market_value) or 0.0 for row in positions)
        summary = PortfolioSummary(fund_count=len(positions), total_market_value=total)
        items: list[PositionItem] = []
        for row in positions:
            nav = navs.get(row.fund_code)
            fund = funds.get(row.fund_code)
            trades = ledger.get((row.account_id, row.fund_code), [])
            projected = project_ledger(trades) if trades else None
            figures = position_figures(
                market_value=row.market_value,
                shares=projected.shares if projected else row.shares,
                cost_amount=projected.cost_amount if projected else row.cost_amount,
                average_cost_nav=None if projected else row.average_cost_nav,
                profit_loss=None if projected else row.profit_loss,
                unit_nav=nav.unit_nav if nav else None,
            )
            summary.total_cost += figures.cost_amount or 0.0
            summary.total_profit_loss += figures.profit_loss or 0.0
            if nav and nav.fetched_at:
                summary.data_updated_at = max(summary.data_updated_at or nav.fetched_at, nav.fetched_at)
            items.append(
                PositionItem(
                    id=row.id,
                    account_id=row.account_id,
                    fund_code=row.fund_code,
                    fund_name=fund.fund_name if fund else None,
                    shares=figures.shares,
                    market_value=row.market_value,
                    cost_amount=figures.cost_amount,
                    average_cost_nav=figures.average_cost_nav,
                    profit_loss=figures.profit_loss,
                    profit_loss_rate=figures.profit_loss_rate,
                    position_ratio=position_weight(row.market_value, total),
                    shares_derived=figures.shares_derived,
                    cost_derived=figures.cost_derived,
                    average_cost_nav_derived=figures.average_cost_nav_derived,
                    profit_derived=figures.profit_derived,
                    nav_date=nav.nav_date if nav else None,
                    updated_at=row.updated_at,
                    version=row.version,
                )
            )
        if summary.total_cost > 0 and all(
            item.cost_amount is not None and item.profit_loss is not None for item in items
        ):
            summary.total_profit_loss_rate = position_figures(
                cost_amount=summary.total_cost, profit_loss=summary.total_profit_loss
            ).profit_loss_rate
        complete = all(
            finite_number(row.market_value) is not None and (row.market_value or 0) >= 0 for row in positions
        )
        warnings = []
        if not complete:
            warnings.append("部分持仓市值缺失或无效，汇总仅覆盖已知金额，不能计算完整操作比例")
        if any(item.cost_amount is None or item.profit_loss is None for item in items):
            warnings.append("部分持仓成本未知，成本与盈亏汇总不代表完整账本")
        items.sort(key=lambda item: item.market_value if item.market_value is not None else -1, reverse=True)
        return PortfolioResearchSnapshot(
            account_id=account_id,
            status="available" if positions else "empty",
            captured_at=utc_now(),
            summary=summary,
            positions=items,
            market_values_complete=complete,
            warnings=warnings,
        )

    async def get_position(self, user_id: int, account_id: int, fund_code: str) -> PositionItem | None:
        """单条持仓及其派生指标（spec 3.5.2 的字段）."""
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
        """创建或更新持仓快照，用乐观锁防止并发覆盖.

        已经有 BUY/SELL 流水的基金，这里只接受 持有金额 和 首次购买日期：
        份额 和 持仓成本 归流水账本所有，
        让快照去覆盖它们，等于悄悄撤销掉已经记录在案的成交。

        没有流水时，表单只给出成对的数据 —— 金额 配 收益，或者 份额 配 持仓成本价 ——
        其余金额数字都由这一对推出来。
        重述任意一对，就把它替代掉的落库数值作废，
        这样导入留下的旧成本和刚手填的收益不会都声称自己是对的。

        Raises:
            AccountNotFoundError: 账户不存在或属于他人 → 上游 HTTP 404。
            PositionConflictError: `version` 不匹配 → 上游 HTTP 409。
        """
        async with transaction_scope():
            await self.ensure_account(user_id, account_id, for_update=True)
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
                shares=fields.get("shares"),
                cost_amount=fields.get("cost_amount"),
                average_cost_nav=fields.get("average_cost_nav"),
                market_value=fields.get("market_value"),
                profit_loss=fields.get("profit_loss"),
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
        """判定这笔委托归属哪个交易时段（截止点 15:00 之前还是之后），并取回对应的净值.

        Raises:
            NavNotPublishedError: 该基金在确认日当天或更早都没有净值，
                所以这笔委托还算不出份额。
        """
        confirm = settlement_date(trade_date, after_cutoff)
        row = await fund_repository.get_nav_on_or_before(fund_code, confirm)
        if row is None or not row.unit_nav:
            raise NavNotPublishedError(fund_code, confirm)
        return _PricedOrder(confirm_date=confirm, nav=row.unit_nav, nav_date=row.nav_date)

    @staticmethod
    def _opening_row(position: PortfolioPosition | None, unit_nav: float | None) -> LedgerRow | None:
        """账本必须先有的那行期初持仓 —— 前提是持仓比流水更早存在.

        靠截图导入的基金，以前只要补记一笔买入，
        它的持仓成本就会被重写成只有这一笔：
        快照上写着 1019.19，账本里只剩 1000。
        把快照作为期初行结转进账本之后，
        新的一笔就是在原有持仓上做加法，而不是取而代之。

        这行种子取自*解析后*的数值，不是直接读落库的列：
        按金额 录入的快照只存了 市值 和 收益，份额与成本要算出来才存在。
        当初直接读列，这类持仓的期初行等于空的，
        第一次 加仓 或 定投 看起来就像把整个持仓清掉了。
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
        # 有份额但既没有成本也没有收益的行，没有成本可以结转。
        # 按盈亏平衡来读，是唯一不会凭空造出盈利或亏损的取法。
        cost = figures.cost_amount if figures.cost_amount is not None else position.market_value
        if cost is None:
            return None
        return LedgerRow(kind="BUY", shares=figures.shares, amount=cost)

    def _projection_rows(
        self, position: PortfolioPosition | None, rows: list[LedgerRow], unit_nav: float | None
    ) -> list[LedgerRow]:
        """投影这条持仓所用的那些流水行，包含期初余额.

        预览和写入都走这里，
        所以保存前展示给用户的数字，就是保存后真正算出来的数字。
        """
        if rows:
            return rows
        opening = self._opening_row(position, unit_nav)
        return [opening] if opening else []

    @staticmethod
    async def _rows_of(user_id: int, account_id: int, fund_code: str) -> list[LedgerRow]:
        """投影该基金持仓所用的那份流水."""
        return (await portfolio_repository.ledger_rows(user_id, account_id)).get((account_id, fund_code), [])

    @staticmethod
    async def _unit_nav(fund_code: str) -> float | None:
        """快照的 市值 是按哪个价格标记的，用于折算期初种子."""
        latest = await fund_repository.get_latest_nav(fund_code)
        return latest.unit_nav if latest and latest.unit_nav else None

    async def _planned_rows(
        self, user_id: int, account_id: int, fund_code: str
    ) -> tuple[PortfolioPosition | None, list[LedgerRow]]:
        """定价时一并读出：该基金的落库快照，以及它的流水."""
        position = await portfolio_repository.get_position(user_id, account_id, fund_code)
        rows = await self._rows_of(user_id, account_id, fund_code)
        return position, self._projection_rows(position, rows, await self._unit_nav(fund_code))

    async def _ensure_opening(self, user_id: int, account_id: int, fund_code: str, confirm: date) -> None:
        """在第一行流水落到该基金之前，先把快照里的持仓结转进账本.

        这是 ``_projection_rows`` 的写入侧：预览是拿什么数据定价的，
        就原样把什么数据落库，
        两者不可能在"这笔新委托之后旧持仓还在不在"上给出不同答案。
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
        """用流水重建某只持仓。定投计划的撤销路径要用，所以对外公开."""
        async with transaction_scope():
            await self.ensure_account(user_id, account_id, for_update=True)
            await self._reproject(user_id, account_id, fund_code)

    async def _reproject(self, user_id: int, account_id: int, fund_code: str) -> None:
        """从流水重新算出持仓的份额、持仓成本和市值.

        每次都拿全部流水整体重算，而不是在旧值上叠一个增量，所以同一只基金不管
        各行流水以什么顺序到达，读回来都是同一个结果。
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
            # 快照在这两列里留下的数字描述的是旧持仓，
            # 不是这份流水现在累加出来的那份。
            reset=["average_cost_nav", "profit_loss"],
            allow_unversioned_update=True,
        )

    @staticmethod
    def _leg(
        fund_code: str, priced: _PricedOrder, rows: list[LedgerRow], delta: OrderDelta, direction: Direction
    ) -> TradeLeg:
        """单只基金的成交前后对比，已经把新增的那一行折进去了."""
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
        """把一笔委托按净值定价，算成它将要写入的流水行.

        预览和写入都走这里，
        所以保存前显示的数字与保存后真正产生的数字完全一致。

        Raises:
            NavNotPublishedError: 涉及的两只基金里任意一只，确认日还没有净值。
            TradeTooLargeError: 卖出那一腿要卖的份额超过持仓实际持有的量。
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
        """这笔委托会把持仓变成什么样 —— 此时还不写任何东西."""
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
        idempotency_key: str | None = None,
    ) -> PositionItem:
        """在同一事务内校验持仓、写完整流水并投影；请求键重放不再次记账."""
        reference = external_ref
        prefix = False
        if idempotency_key is not None:
            if not 1 <= len(idempotency_key) <= 64 or not idempotency_key.strip():
                raise TradeInputError("invalid idempotency key")
            key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
            payload = [
                account_id,
                fund_code,
                operation,
                trade_date.isoformat(),
                after_cutoff,
                amount,
                shares,
                target_code,
                source,
            ]
            payload_hash = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()[:32]
            reference = f"trade:{key_hash}:{payload_hash}"
            prefix = True
        async with transaction_scope():
            await self.ensure_account(user_id, account_id, for_update=True)
            if reference:
                lookup = reference[:39] if prefix else reference
                await portfolio_repository.lock_transaction_ref(user_id, lookup)
                existing = await portfolio_repository.transaction_by_ref(user_id, lookup, prefix=prefix)
                if existing is not None:
                    if (
                        existing.external_transaction_id != reference
                        or existing.account_id != account_id
                        or existing.fund_code != fund_code
                    ):
                        raise TradeIdempotencyConflictError("idempotency_key_reused")
                    position = await self.get_position(user_id, account_id, fund_code)
                    if position is None:
                        raise TradeIdempotencyConflictError("idempotent_position_missing")
                    return position
            return await self._record_trade_locked(
                user_id,
                account_id,
                fund_code,
                operation,
                trade_date,
                after_cutoff,
                amount,
                shares,
                target_code,
                source,
                reference,
            )

    async def _record_trade_locked(
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
        """写入这笔委托的流水行，并把被它碰到的每只基金重新投影一遍."""
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
                # 幂等键只挂在第一腿上：一笔委托只对应一个键，
                # 重试时不能把这一对流水再写第二遍。
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
        if position is None:  # 走到这里账户和持仓都已经存在了
            raise AssertionError(f"position vanished after trade on {fund_code}")
        return position

    async def delete_position(self, user_id: int, account_id: int, fund_code: str) -> bool:
        """把一只基金从账户里彻底抹掉：持仓、它的流水、它的定投计划.

        不留任何能把它重新写回来的东西。也不补审计行 ——
        记录就该随持仓一起消失，这是刻意的 ——
        同时删掉该基金的 定投计划，因为活着的计划会在下一个扣款日结算，
        把他刚删掉的那行流水又复活出来。
        """
        async with transaction_scope():
            await self.ensure_account(user_id, account_id, for_update=True)
            deleted = await portfolio_repository.delete_position(user_id, account_id, fund_code)
            if deleted:
                await auto_invest_repository.delete_plans_for_fund(user_id, account_id, fund_code)
            return deleted

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    async def get_summary(self, user_id: int, account_id: int | None = None) -> PortfolioSummary:
        """资产汇总：总市值、收益、当日收益（spec 3.2）."""
        if account_id is not None:
            await self.ensure_account(user_id, account_id)
        positions = await portfolio_repository.list_positions(user_id, account_id)
        summary = PortfolioSummary(fund_count=len(positions))
        latest_at: datetime | None = None
        # 一次批量读取，代替按每只持仓各查一次净值。
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
    # 流水
    # ------------------------------------------------------------------

    async def list_transactions(
        self,
        user_id: int,
        account_id: int | None = None,
        fund_code: str | None = None,
    ) -> list[TransactionItem]:
        """列出流水，附带基金名称."""
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
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    async def _recent_history(fund_codes: list[str]) -> dict[str, list[FundNav]]:
        """各回溯区间要用的净值行，每次调用只做一次批量查询.

        只读一个多月多一点的数据：展示的区间里最长的是 本月收益，
        把每只持仓的全部历史行都拉出来，代价会远远超过答案本身。
        """
        return await fund_repository.get_nav_history_map(
            fund_codes, start_date=business_today() - timedelta(days=_WINDOW_LOOKBACK_DAYS)
        )

    @staticmethod
    def _order_delta(direction: Direction, nav: float, amount: float | None, shares: float | None) -> OrderDelta:
        """把用户给出的数值，按当天净值折算成流水里的份额与金额.

        Raises:
            TradeInputError: 买入 没填金额，或者 卖出 没填份额。
                两者都没法猜 —— 前者买的是未知数量，
                后者卖的是持仓中未知的一部分。
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
        """给落库的持仓补上查询时算出的派生指标."""
        fund = await fund_repository.get_fund(position.fund_code)
        latest = await fund_repository.get_latest_nav(position.fund_code)

        unit_nav = latest.unit_nav if latest else None
        rows = (ledger or {}).get((position.account_id, position.fund_code), [])
        totals = project_ledger(rows) if rows else None
        figures = position_figures(
            market_value=position.market_value,
            shares=totals.shares if totals else position.shares,
            cost_amount=totals.cost_amount if totals else position.cost_amount,
            # 有流水时，这两列描述的是已经不存在的那份持仓。
            average_cost_nav=None if totals else position.average_cost_nav,
            profit_loss=None if totals else position.profit_loss,
            unit_nav=unit_nav,
        )

        nav_rows = history or []
        daily_profit_loss = None
        # 与自选同一口径：披露 0.00% 而净值动了的那天是"没有行情"（QDII 境外休市），
        # 不是"没涨没跌"。昨日收益必须跟着同一个判断走，否则百分比是空的、钱却有一笔。
        previous = (
            nav_rows[-2].unit_nav
            if latest is not None and len(nav_rows) >= 2 and nav_rows[-1].nav_date == latest.nav_date
            else None
        )
        daily_return = disclosed_change(previous, latest.unit_nav, latest.daily_return) if latest else None
        if daily_return is not None and position.market_value:
            daily_profit_loss = daily_return * position.market_value / 100.0

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

        # 首次购买确认日 由流水维护；没有流水时就是快照里记的那个日期，
        # 持有天数 直接从它开始数。
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
            # 这几个标记一旦置位，录入表单就不把对应数值填进输入框：
            # 这一行其实没存过这些数字，就不能让它们看起来像既定事实。
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
        """把账户数据行映射成对应的 schema."""
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
