"""账户域模型：账户、当前持仓与流水记录."""

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseModel
from app.utils.clock import utc_now


class PortfolioAccount(BaseModel, table=True):
    """用户的一个基金持仓账户（例如 支付宝、天天基金、手工账户）.

    source_app 只是一个标签 —— 它既不代表与第三方平台的可用连接，也不存放任何
    第三方凭证。
    """

    __tablename__ = "portfolio_account"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    source_app: str | None = Field(default=None, max_length=50)
    account_type: str = Field(default="manual", max_length=30)
    import_mode: str = Field(default="manual", max_length=30)
    last_imported_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )

    # 同一用户的两个账户不会重名：账户在选择器里只按名称列出，重名会让用户读不懂
    # 自己选的是哪个，而不只是难看一点。
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_account_user_name"),)


class PortfolioPosition(BaseModel, table=True):
    """某个账户内某只基金的当前持仓.

    只要这只基金的 BUY/SELL 流水有行，``shares`` 与 ``cost_amount`` 就是这些流水的
    投影 —— 写入交易时两者都会重算。没有流水时，它们就是同步持仓当时记下的数字。
    ``market_value`` 永远是快照值，所以改它不会碰到流水。收益率、当日收益、占比这些
    派生指标在查询时算，不落库。
    """

    __tablename__ = "portfolio_position"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)

    shares: float | None = Field(default=None)
    cost_amount: float | None = Field(default=None)
    average_cost_nav: float | None = Field(default=None)
    market_value: float | None = Field(default=None)
    profit_loss: float | None = Field(default=None)

    # 这笔买入是哪一天确认的。基金对 15:00 截止点之前下的单按当日净值定价，
    # 之后按下一个交易日的净值定价，所以截止点规则在写入时就折算成了这一个
    # 日历日，而不是存成一个墙钟时刻让用户去猜。有流水时，这里取最早那笔
    # BUY 的确认日，持有天数就是从这一天开始数出来的。
    purchase_date: date | None = Field(default=None)

    # 乐观锁版本号 —— 导入与手动编辑并发时返回 409，绝不静默覆盖
    version: int = Field(default=1)
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )

    __table_args__ = (UniqueConstraint("account_id", "fund_code", name="uq_position_account_fund"),)


class AutoInvestPlan(BaseModel, table=True):
    """定投计划：在固定周期按固定金额买入的长期约定.

    真正扣款的是平台，不是本应用；计划记的是用户说自己配了什么。结算计划时写入的是
    普通买入流水，这样持仓的份额与成本始终以流水为唯一来源。
    """

    __tablename__ = "auto_invest_plan"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)

    amount: float = Field()
    frequency: str = Field(default="weekly", max_length=20)
    # weekly/biweekly 时是 ISO 周内日 1-7；monthly 时是当月几号，短月按各平台的
    # 惯例钳制到当月最后一天。
    run_day: int = Field(default=1)
    start_date: date
    end_date: date | None = Field(default=None)
    active: bool = Field(default=True)
    # 已经写成买入流水的最后一个扣款日。留着它，长时间断档之后的补跑才是幂等的。
    last_run_date: date | None = Field(default=None)

    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": utc_now},
    )


class Transaction(BaseModel, table=True):
    """一笔流水，或者一次调整记录.

    BUY 与 SELL 行是持仓投影的依据，所以它们带着折算出的 ``confirm_date`` 和这些份额
    定价所用的净值。IMPORT_ADJUSTMENT 与 MANUAL_ADJUSTMENT 行只用于审计：记下某次快照
    覆盖替换掉了什么，不参与投影。
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    account_id: int = Field(foreign_key="portfolio_account.id", index=True)
    fund_code: str = Field(max_length=12, index=True)
    transaction_type: str = Field(max_length=30)
    trade_date: date = Field(index=True)
    # 这笔订单按哪个交易日的净值定价：正常就是 trade_date，15:00 之后提交、
    # 或提交在非交易日时顺延到下一个交易日。
    confirm_date: date | None = Field(default=None)
    shares: float | None = Field(default=None)
    nav: float | None = Field(default=None)
    amount: float | None = Field(default=None)
    fee: float | None = Field(default=None)
    source: str = Field(default="manual", max_length=50)
    external_transaction_id: str | None = Field(default=None, max_length=100)
