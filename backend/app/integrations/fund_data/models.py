"""基金数据源适配器返回的领域模型.

适配器必须把原始返回换成这些内部模型——第三方的字段结构不会透传到前端
（MVP spec 5.5）.
"""

from datetime import date

from pydantic import BaseModel


class FundExternalRecord(BaseModel):
    """搜索命中的一只基金：代码、名称和最新公布净值."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    latest_nav: float | None = None
    latest_accumulated: float | None = None
    nav_date: date | None = None
    daily_return: float | None = None


class FundExternalProfile(BaseModel):
    """基金主数据：标识、类型、管理公司、基金经理、成立日期."""

    fund_code: str
    fund_name: str
    fund_type: str | None = None
    company: str | None = None
    manager_name: str | None = None
    inception_date: date | None = None
    asset_size: str | None = None


class FundExternalNav(BaseModel):
    """某只基金的一个净值点（单位净值 + 累计净值）."""

    fund_code: str
    nav_date: date
    unit_nav: float | None = None
    accumulated_nav: float | None = None
    daily_return: float | None = None


class FundExternalManager(BaseModel):
    """基金经理基本信息."""

    fund_code: str
    manager_name: str | None = None


class FundExternalHolding(BaseModel):
    """基金披露持仓里的一只股票，带它所属的报告季度."""

    fund_code: str
    stock_code: str
    stock_name: str | None = None
    weight: float | None = None  # 占净值比例，单位是百分点
    shares: float | None = None  # 持股数，按上游原样以万股计
    market_value: float | None = None  # 持仓市值，单位万元
    quarter: str | None = None  # 形如 "2026年2季度"


class FundExternalIndustry(BaseModel):
    """按披露口径，某个行业占基金净值的比例."""

    fund_code: str
    industry: str
    weight: float | None = None  # 占净值比例，百分点
    market_value: float | None = None
    as_of: date | None = None  # 该报告期的截止时间


class StockExternalQuote(BaseModel):
    """个股的一条行情，覆盖 A股 / 港股 / 美股."""

    symbol: str  # 带上游前缀的标的代码，如 sz300570、hk01810、gb_aapl
    name: str | None = None
    price: float | None = None
    change_pct: float | None = None  # 百分点，与基金日涨幅口径一致
    quote_time: str | None = None  # 上游原始时间戳，各市场格式不一样


class IndexExternalQuote(BaseModel):
    """业绩比较基准指数某一个交易日的收盘价（基金对比线用）."""

    index_code: str
    trade_date: date
    close: float


class MarketExternalQuote(BaseModel):
    """一只上市标的的实时快照，覆盖 A股 / 港股 / 美股 / 指数.

    金额用标的自身的币种：``amount`` 是基础单位（元/港元/美元），两个市值字段
    则按上游原样保持亿为单位.
    """

    symbol: str  # 腾讯的规范代码：sh600519、sz300570、hk01810、usAAPL.OQ、sh000001
    listing_code: str | None = None  # 上游自己的代码，如 AAPL.OQ——K 线要带这个后缀
    kind: str  # "stock" | "index"
    name: str | None = None
    currency: str | None = None  # CNY / HKD / USD
    price: float | None = None
    prev_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    change: float | None = None  # 价格绝对变动额
    change_pct: float | None = None  # 百分点，与基金日涨幅口径一致
    volume: float | None = None  # 上游原始单位，见 volume_unit
    volume_unit: str | None = None  # A股/指数为手，港股/美股为股
    amount: float | None = None
    turnover_rate: float | None = None  # 换手率，百分点
    amplitude: float | None = None  # 振幅，百分点
    pe: float | None = None  # 市盈率，仅个股有
    pb: float | None = None  # 市净率，仅 A股有
    float_market_cap: float | None = None  # 流通市值，单位亿
    total_market_cap: float | None = None  # 总市值，单位亿
    week52_high: float | None = None
    week52_low: float | None = None
    quote_time: str | None = None  # 已归一化为 "YYYY-MM-DD HH:MM:SS"


class CandleExternalBar(BaseModel):
    """一根 OHLCV K 线；``volume`` 沿用行情自身的单位."""

    trade_date: date
    open: float
    close: float
    high: float
    low: float
    volume: float | None = None


class MinuteExternalPoint(BaseModel):
    """交易时段内的一个分钟点.

    ``volume`` 和 ``amount`` 是单分钟的值，由上游的累计量、累计额差分得到；
    ``average_price`` 只对个股有意义。单日分时的 ``trade_date`` 保持 None，
    五日序列因为点跨了好几天才要填上.
    """

    time: str  # "HH:MM"
    price: float
    volume: float | None = None
    amount: float | None = None
    average_price: float | None = None
    trade_date: date | None = None


class MinuteExternalSeries(BaseModel):
    """一条分时线，外加画它的坐标轴需要的两个数."""

    trade_date: date | None = None  # 序列里最近的那个交易日
    prev_close: float | None = None  # 分时图要画的那条水平基准线
    points: list[MinuteExternalPoint] = []


class CompanyExternalProfile(BaseModel):
    """上市公司主数据（只有 A股 有；其他市场拿不到档案）."""

    symbol: str
    name: str | None = None
    industry: str | None = None
    region: str | None = None
    list_date: date | None = None
    main_business: str | None = None
    description: str | None = None
    employees: float | None = None
    chairman: str | None = None
    concepts: list[str] = []
