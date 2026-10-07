"""账户域仓储：账户、持仓（乐观锁）与流水."""

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

# 哪些流水行给持仓加份额、哪些减份额。转换是两行 —— 源基金赎出一行、目标基金买入
# 一行，按同一个交易日定价，所以它读起来是一卖一买，而不是第三种性质的钱。
LEDGER_IN = ("OPENING", "BUY", "AUTO_INVEST", "CONVERT_IN")
LEDGER_OUT = ("SELL", "CONVERT_OUT")


class PortfolioRepository:
    """账户、持仓与流水的异步数据访问."""

    # ------------------------------------------------------------------
    # 账户
    # ------------------------------------------------------------------

    async def list_accounts(self, user_id: int) -> list[PortfolioAccount]:
        """按创建顺序列出该用户的账户."""
        async with get_async_session() as session:
            result = await session.execute(
                select(PortfolioAccount)
                .where(col(PortfolioAccount.user_id) == user_id)
                .order_by(col(PortfolioAccount.id))
            )
            return list(result.scalars().all())

    async def get_account(self, user_id: int, account_id: int) -> PortfolioAccount | None:
        """读取该用户名下的一个账户."""
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
        """按名称查账户，忽略大小写和首尾空格.

        唯一约束比的是字节，"支付宝" 和 "支付宝 " 都会各占一行；服务层先用这个方法
        把这种近似重名挡在前面。
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
        """创建一个资产组合账户."""
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
        """账户改名，或更换它的来源标签."""
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
        """删除账户，连同它的持仓、流水和导入记录一起删掉."""
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
        """导入确认之后，把 last_imported_at 置为当前时间."""
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
    # 持仓
    # ------------------------------------------------------------------

    async def list_positions(self, user_id: int, account_id: int | None = None) -> list[PortfolioPosition]:
        """列出持仓，可用 account_id 收窄到一个账户."""
        async with get_async_session() as session:
            statement = select(PortfolioPosition).where(col(PortfolioPosition.user_id) == user_id)
            if account_id is not None:
                statement = statement.where(col(PortfolioPosition.account_id) == account_id)
            result = await session.execute(statement.order_by(col(PortfolioPosition.fund_code)))
            return list(result.scalars().all())

    async def get_position(self, user_id: int, account_id: int, fund_code: str) -> PortfolioPosition | None:
        """按 (账户, 基金) 读取一条持仓."""
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
        """在已经开启的会话里读取一条持仓."""
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
        """带乐观锁的持仓插入或更新.

        Args:
            user_id: 归属用户 id。
            account_id: 目标账户 id。
            fund_code: 6 位基金代码。
            expected_version: 调用方读到的版本号；更新时必填，首次插入传 None。
                版本不一致时返回 None（→ HTTP 409）。
            shares: 持有份额。
            cost_amount: 持仓成本金额。
            average_cost_nav: 持仓均价，即每份的成本。
            market_value: 当前市值。
            profit_loss: 累计盈亏。
            purchase_date: 首次购买确认日，持有天数从这一天开始算。
            reset: 应用完上面这些值之后要清空的列名，让这些数字重新回到查询时派生。

        Returns:
            更新后的持仓；版本冲突或该行不存在时返回 None。

        字段为 None 表示调用方没有提供，已存的值原样保留：spec 3.7.1 允许部分快照，
        同时禁止凭空造出数据。
        """
        async with get_async_session() as session:
            existing = await self._select_position(session, user_id, account_id, fund_code)

            if existing is None:
                if expected_version is not None:
                    return None  # 调用方以为行已经存在，按版本冲突处理
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
                # 并发的首次写入抢先落了这一行：改成更新它，而不是把唯一约束冲突
                # 抛成一个 500。
                existing = await self._select_position(session, user_id, account_id, fund_code)
                if existing is None:
                    return None

            if expected_version is not None and existing.version != expected_version:
                return None  # 乐观锁版本冲突

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
            # `reset` 是调用方在说“把这个数字交回派生口径”；键要和上面同一份集合比对，
            # 所以不可能只凭一个列名就清空某一列。
            for key in reset:
                if key in supplied:
                    setattr(existing, key, None)
            existing.version = (existing.version or 1) + 1
            existing.updated_at = utc_now()
            session.add(existing)
            await session.flush()
            return existing

    async def delete_position(self, user_id: int, account_id: int, fund_code: str) -> bool:
        """删掉一条持仓记录."""
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
            # 流水跟着这一行一起删：残留的 BUY/SELL/AUTO_INVEST 行，会在这个代码上
            # 再有交易的那一刻把持仓重新投影出来，看起来就像删除从没生效。
            await session.execute(
                sa_delete(Transaction).where(
                    col(Transaction.user_id) == user_id,
                    col(Transaction.account_id) == account_id,
                    col(Transaction.fund_code) == fund_code,
                )
            )
            return True

    # ------------------------------------------------------------------
    # 流水
    # ------------------------------------------------------------------

    async def list_transactions(
        self,
        user_id: int,
        account_id: int | None = None,
        fund_code: str | None = None,
        limit: int = 200,
    ) -> list[Transaction]:
        """按时间倒序列出流水，可按账户和基金代码过滤."""
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
        """按成交先后，把每一行流水按 (账户, 基金) 分组.

        整本流水一次读完：投影一只基金要遍历它的每一行，因为部分赎回是按当时持仓
        结转的均价把成本带出去的。OPENING 行是流水起步时的那份快照，和买入一样增加
        持仓。调整类行不在其中 —— 它们记的是某次快照覆盖，不是交易。
        """
        async with get_async_session() as session:
            statement = (
                select(Transaction)
                .where(
                    col(Transaction.user_id) == user_id,
                    col(Transaction.transaction_type).in_(LEDGER_IN + LEDGER_OUT),
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
                        kind="SELL" if row.transaction_type in LEDGER_OUT else "BUY",
                        shares=row.shares or 0.0,
                        amount=row.amount or 0.0,
                    )
                )
            return grouped

    async def earliest_confirm_date(self, user_id: int, account_id: int, fund_code: str) -> date | None:
        """最早那笔买入的确认日，持有天数从这里开始数."""
        async with get_async_session() as session:
            statement = (
                select(col(Transaction.confirm_date))
                .where(
                    col(Transaction.user_id) == user_id,
                    col(Transaction.account_id) == account_id,
                    col(Transaction.fund_code) == fund_code,
                    col(Transaction.transaction_type).in_(LEDGER_IN),
                    col(Transaction.confirm_date).is_not(None),
                )
                .order_by(col(Transaction.confirm_date))
                .limit(1)
            )
            return (await session.execute(statement)).scalar_one_or_none()

    async def has_transaction_ref(self, user_id: int, external_transaction_id: str) -> bool:
        """判断某次幂等写入是否已经落库，比如定投的某一期."""
        async with get_async_session() as session:
            result = await session.execute(
                select(col(Transaction.id))
                .where(
                    col(Transaction.user_id) == user_id,
                    col(Transaction.external_transaction_id) == external_transaction_id,
                )
                .limit(1)
            )
            return result.scalar_one_or_none() is not None

    async def delete_transactions_by_source(self, user_id: int, source: str) -> int:
        """删掉某个功能生成的全部流水，撤掉它时不留残余."""
        async with get_async_session() as session:
            result = await session.execute(
                sa_delete(Transaction).where(col(Transaction.user_id) == user_id, col(Transaction.source) == source)
            )
            return result.rowcount

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
        """追加一条流水/审计记录."""
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
