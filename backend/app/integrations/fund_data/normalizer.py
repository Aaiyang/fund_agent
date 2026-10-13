"""把 AKShare 等上游的原始返回归一化成内部领域模型.

所有解析都按防御式写：第三方表里的列名和取值格式会随 AKShare 版本变，所以每个
字段都当成可缺、每次转换都容忍脏值.
"""

import re
from datetime import date, datetime
from typing import Any

from app.core.logging import logger
from app.integrations.fund_data.models import (
    CandleExternalBar,
    CompanyExternalProfile,
    FundExternalHolding,
    FundExternalIndustry,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
    IndexExternalQuote,
    MarketExternalQuote,
    MinuteExternalPoint,
    MinuteExternalSeries,
    StockExternalQuote,
)

_PERCENT_SUFFIX = re.compile(r"%\s*$")


def to_float(value: Any) -> float | None:
    """把原始单元格（数字、数字字符串、'1.23%'、'--'）转成 float."""
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _PERCENT_SUFFIX.sub("", str(value).strip().replace(",", ""))
    if not text or text in _MISSING_TOKENS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    """把原始日期单元格（date、datetime、'YYYY-MM-DD'、'YYYYMMDD'）转成 date.

    解析不出的一律给 None：pandas 缺日期时交来的是 NaT，去碰它不会返回 None，
    而是直接抛异常.
    """
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return None


# AKShare/pandas 用来表示"没有值"的哨兵；NaT 到我们手里时 str() 出来是 'NaT'，
# NaN 则是一个不等于自身的 float。
_MISSING_TOKENS = {"", "--", "-", "—", "None", "nan", "NaN", "NaT", "nat"}


def _is_missing(value: Any) -> bool:
    """None、NaN、NaT 以及 AKShare 吐出的那些占位字符串都算缺值."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    if str(value).strip() in _MISSING_TOKENS:
        return True
    # pandas 的 NaT 看着像 datetime，真去用它就炸
    return type(value).__name__ == "NaTType"


def _pick(record: dict[str, Any], *keys: str) -> Any:
    """在候选列名里返回第一个有值的."""
    for key in keys:
        value = record.get(key)
        if not _is_missing(value):
            return value
    return None


def normalize_fund_record(record: dict[str, Any]) -> FundExternalRecord | None:
    """把一行搜索/排行数据归一化成 FundExternalRecord."""
    fund_code = _pick(record, "基金代码", "fund_code", "代码")
    fund_name = _pick(record, "基金简称", "基金全称", "fund_name", "名称")
    if not fund_code:
        return None
    return FundExternalRecord(
        fund_code=str(fund_code).strip().zfill(6),
        fund_name=str(fund_name or "").strip(),
        fund_type=str(_pick(record, "基金类型", "fund_type")).strip() or None if _pick(record, "基金类型") else None,
        latest_nav=to_float(_pick(record, "单位净值", "最新净值", "nav")),
        latest_accumulated=to_float(_pick(record, "累计净值", "累计单位净值")),
        nav_date=to_date(_pick(record, "日期", "净值日期", "nav_date")),
        daily_return=to_float(_pick(record, "日增长率", "日涨跌幅", "daily_return")),
    )


def _text(info: dict[str, Any], limit: int, *keys: str) -> str | None:
    """候选键里第一个能用的值，截到 `limit` 个字符."""
    value = _pick(info, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def normalize_profile_rows(rows: list[dict[str, Any]], fund_code: str) -> FundExternalProfile | None:
    """归一化 `fund_individual_basic_info_xq` 那种 item/value 行."""
    if not rows:
        return None
    info: dict[str, Any] = {}
    for row in rows:
        key = str(_pick(row, "item", "项目", "选项") or "").strip()
        if key:
            info[key] = _pick(row, "value", "值", "数值")

    fund_name = str(_pick(info, "基金简称", "基金全称") or "").strip()
    if not fund_name:
        logger.debug("fund_profile_name_missing", fund_code=fund_code)
        return None

    # 这一格在 AKShare 各版本里改过名：成立日期、成立日期/规模、成立时间都真实
    # 存在过，键名少认一个就会静默地产出 None。
    inception_raw = _pick(info, "成立日期", "成立日期/规模", "成立时间", "发行日期")
    inception = None
    if inception_raw:
        text = str(inception_raw).strip()
        # "2021-01-01/2.34亿" 把规模跟在日期后面；但斜杠分隔的日期不能被拆开，
        # 所以先拿整个值试一次解析。
        inception = to_date(text) or to_date(text.split("/")[0])

    return FundExternalProfile(
        fund_code=fund_code,
        fund_name=fund_name,
        fund_type=str(_pick(info, "基金类型") or "").strip() or None,
        company=str(_pick(info, "基金管理人", "基金公司") or "").strip() or None,
        manager_name=str(_pick(info, "基金经理") or "").strip() or None,
        inception_date=inception,
        asset_size=_text(info, 50, "最新规模", "基金规模", "规模"),
    )


def normalize_nav_rows(
    unit_rows: list[dict[str, Any]],
    accumulated_rows: list[dict[str, Any]],
    fund_code: str,
) -> list[FundExternalNav]:
    """按净值日期把单位净值行和累计净值行合并起来."""
    accumulated_by_date = {
        nav_date: to_float(_pick(row, "累计净值"))
        for row in accumulated_rows
        if (nav_date := to_date(_pick(row, "净值日期", "日期"))) is not None
    }

    navs: list[FundExternalNav] = []
    for row in unit_rows:
        nav_date = to_date(_pick(row, "净值日期", "日期"))
        if nav_date is None:
            continue
        navs.append(
            FundExternalNav(
                fund_code=fund_code,
                nav_date=nav_date,
                unit_nav=to_float(_pick(row, "单位净值")),
                accumulated_nav=accumulated_by_date.get(nav_date),
                daily_return=to_float(_pick(row, "日增长率")),
            )
        )
    navs.sort(key=lambda nav: nav.nav_date, reverse=True)
    return navs


def normalize_index_rows(rows: list[dict[str, Any]], index_code: str) -> list[IndexExternalQuote]:
    """把指数日频表转成按日期升序的行情点，每点只带 date 与 close.

    AKShare 的指数接口在不同版本、不同源之间列名并不统一（新浪是小写英文，东财
    是中文），所以两种写法都收，用不了的行直接丢掉.
    """
    quotes: list[IndexExternalQuote] = []
    for row in rows:
        trade_date = to_date(_pick(row, "date", "日期", "trade_date"))
        close = to_float(_pick(row, "close", "收盘", "close_price"))
        if trade_date is None or close is None or close <= 0:
            continue
        quotes.append(IndexExternalQuote(index_code=index_code, trade_date=trade_date, close=close))
    quotes.sort(key=lambda quote: quote.trade_date)
    return quotes


_QUARTER_PATTERN = re.compile(r"(\d{4})年(\d)季度")


def parse_quarter(label: Any) -> tuple[int, int] | None:
    """给报告期排序用的键，形如 ``2026年2季度股票投资明细``."""
    if label is None:
        return None
    match = _QUARTER_PATTERN.search(str(label))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def normalize_holding_rows(rows: list[dict[str, Any]], fund_code: str) -> list[FundExternalHolding]:
    """把 ``fund_portfolio_hold_em`` 的行转成带报告季度的持仓."""
    holdings: list[FundExternalHolding] = []
    for row in rows:
        stock_code = _pick(row, "股票代码", "证券代码", "stock_code")
        if stock_code is None:
            continue
        quarter_label = _pick(row, "季度", "period")
        holdings.append(
            FundExternalHolding(
                fund_code=fund_code,
                stock_code=str(stock_code).strip(),
                stock_name=str(_pick(row, "股票名称", "证券简称", "stock_name") or "").strip() or None,
                weight=to_float(_pick(row, "占净值比例", "占净值比例(%)", "weight")),
                shares=to_float(_pick(row, "持股数", "持仓数量")),
                market_value=to_float(_pick(row, "持仓市值", "市值")),
                quarter=str(quarter_label).strip() if quarter_label else None,
            )
        )
    return holdings


def sina_symbol(stock_code: str) -> str | None:
    """把持仓代码换成行情代码；市场信息藏在代码形状里.

    持仓表没有市场列，所以 6 位数字是中国内地上市（首位 5/6/9 归上海，其余归
    深圳），5 位数字是港股，带字母的是美股.
    """
    code = stock_code.strip()
    if code.isdigit():
        if len(code) == 6:
            return ("sh" if code[0] in "569" else "sz") + code
        if len(code) == 5:
            return "hk" + code
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,9}", code):
        return "gb_" + code.lower()
    return None


_SINA_LINE = re.compile(r'var hq_str_(?P<symbol>\w+)="(?P<body>[^"]*)"')


def parse_sina_quotes(payload: str) -> list[StockExternalQuote]:
    """解析批量行情返回；每个市场的字段排布都不一样."""
    quotes: list[StockExternalQuote] = []
    for match in _SINA_LINE.finditer(payload):
        symbol = match.group("symbol")
        fields = match.group("body").split(",")
        if len(fields) < 4 or not fields[0]:
            continue
        if symbol.startswith("gb_"):
            # 名称,现价,涨跌幅,时间,涨跌额,昨收,开盘,最高,最低,...
            quotes.append(
                StockExternalQuote(
                    symbol=symbol,
                    name=fields[0],
                    price=to_float(fields[1]),
                    change_pct=to_float(fields[2]),
                    quote_time=fields[3] or None,
                )
            )
        elif symbol.startswith("hk"):
            # 英文名,名称,昨收,开盘,最高,最低,现价,涨跌额,涨跌幅,...,日期,时间
            quotes.append(
                StockExternalQuote(
                    symbol=symbol,
                    name=fields[1],
                    price=to_float(fields[6]),
                    change_pct=to_float(fields[8]),
                    quote_time=" ".join(fields[-2:]) if len(fields) > 2 else None,
                )
            )
        else:
            # A股: 名称,今开,昨收,现价,最高,最低,...,日期(30),时间(31)
            previous_close = to_float(fields[2])
            price = to_float(fields[3])
            change_pct = None
            if previous_close and price is not None:
                change_pct = round((price - previous_close) / previous_close * 100, 4)
            quotes.append(
                StockExternalQuote(
                    symbol=symbol,
                    name=fields[0],
                    price=price,
                    change_pct=change_pct,
                    quote_time=" ".join(fields[30:32]) if len(fields) > 31 else None,
                )
            )
    return quotes


_TENCENT_LINE = re.compile(r'v_(?P<symbol>[0-9A-Za-z.]+)="(?P<body>[^"]*)"')

_INDEX_SYMBOL_PREFIXES = ("sh000", "sz399", "bj899")

_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _tencent_node(payload: Any, symbol: str) -> dict[str, Any]:
    """行情返回里属于单个标的的那一层对象.

    接口表示"没有数据"时给的是裸的 ``"data": []``，不是空对象，所以每往下取一层
    都得先判类型.
    """
    container = payload.get("data") if isinstance(payload, dict) else None
    node = container.get(symbol) if isinstance(container, dict) else None
    return node if isinstance(node, dict) else {}


def market_kind(symbol: str) -> str:
    """从代码形状判断是指数还是个股；哪张上市表都没有市场列.

    ``sh000*``、``sz399*``、``bj899*`` 是沪、深、北交所指数号段。号段重叠是有意为之：
    ``sh000001`` 是上证指数，``sz000001`` 却是平安银行.
    """
    return "index" if symbol.startswith(_INDEX_SYMBOL_PREFIXES) else "stock"


def tencent_symbol(stock_code: str) -> str | None:
    """把上市代码换成腾讯的代码形式.

    市场推断和 :func:`sina_symbol` 一样靠代码形状，区别是美股 ticker 要保持大写
    （接口在美股这边区分大小写），而已带前缀的代码原样透传，方便调用方来回转.
    """
    code = stock_code.strip()
    if re.fullmatch(r"(?:sh|sz|bj|hk)\d{4,6}|us[A-Z][A-Z.]{0,10}", code):
        return code
    if code.isdigit():
        if len(code) == 6:
            return ("sh" if code[0] in "569" else "sz") + code
        if len(code) in (4, 5):
            return "hk" + code.zfill(5)
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z.]{0,11}", code):
        return "us" + code.upper()
    return None


def _quote_time(raw: str) -> str | None:
    """归一化接口在不同市场使用的两种时间戳形状."""
    value = raw.strip()
    if re.fullmatch(r"\d{14}", value):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"
    return value or None


def _field(fields: list[str], index: int) -> float | None:
    return to_float(fields[index]) if index < len(fields) else None


def parse_tencent_quotes(payload: str) -> list[MarketExternalQuote]:
    """解析批量快照返回；字段排布随市场变化.

    下标 1-45 在 A股、港股、美股和指数上是对齐的，再往后就分叉了，所以多出来的
    字段交给下面按市场各写的辅助函数读，而不是共用一张下标表。五档买卖盘是故意
    不解析的：只有盘中才有值，也没有哪个页面要显示它.
    """
    quotes: list[MarketExternalQuote] = []
    for match in _TENCENT_LINE.finditer(payload):
        symbol = match.group("symbol")
        fields = match.group("body").split("~")
        if len(fields) < 46 or not fields[1]:
            continue
        kind = market_kind(symbol)
        base = fields[35].split("/")
        quotes.append(
            MarketExternalQuote(
                symbol=symbol,
                listing_code=fields[2].strip() or None,
                kind=kind,
                name=fields[1].strip() or None,
                currency=_quote_currency(fields),
                price=_field(fields, 3),
                prev_close=_field(fields, 4),
                open=_field(fields, 5),
                volume=_field(fields, 6),
                volume_unit="手" if symbol.startswith(("sh", "sz", "bj")) else "股",
                quote_time=_quote_time(fields[30]),
                change=_field(fields, 31),
                change_pct=_field(fields, 32),
                high=_field(fields, 33),
                low=_field(fields, 34),
                # A股和指数把 "price/volume/amount" 挤在第 35 位，成交额单位是元；
                # 港股和美股那一位只有裸价格，元为单位的成交额在第 37 位。
                amount=_field(base, 2) if len(base) == 3 else _field(fields, 37),
                # 港股把换手率恒置为 0，停牌的股票也报 0；这两种都不值得显示，
                # 一律当成缺值。
                turnover_rate=_field(fields, 38) or None,
                pe=None if kind == "index" else _field(fields, 39),
                amplitude=_field(fields, 43),
                float_market_cap=_field(fields, 44),
                total_market_cap=_field(fields, 45),
                pb=None if kind == "index" else _quote_pb(fields),
                week52_high=_quote_week52(fields)[0],
                week52_low=_quote_week52(fields)[1],
            )
        )
    return quotes


def _quote_currency(fields: list[str]) -> str | None:
    for index in (82, 75, 35):
        value = fields[index].strip() if index < len(fields) else ""
        if _CURRENCY.fullmatch(value):
            return value
    return None


def _quote_pb(fields: list[str]) -> float | None:
    """市净率在 A股 位于第 46 位；其他市场这一位放的是英文名称."""
    return _field(fields, 46) if len(fields) > 80 else None


def _quote_week52(fields: list[str]) -> tuple[float | None, float | None]:
    """52 周最高/最低：A股 在 67/68，港股和美股在 48/49."""
    if len(fields) > 80:
        return _field(fields, 67), _field(fields, 68)
    return _field(fields, 48), _field(fields, 49)


def parse_tencent_candles(payload: dict[str, Any], symbol: str) -> list[CandleExternalBar]:
    """从 K 线返回里取出单个标的的 K 线数组.

    行的顺序是 date, open, **close, high**, low, volume，并不是 OHLC。港股的行尾部
    还可能多带一个公司行为的 dict，所以取值一律从左边按下标数，不能写成去掉
    末尾那一项.
    """
    node = _tencent_node(payload, symbol)
    for key in ("qfqday", "day", "qfqweek", "week", "qfqmonth", "month"):
        rows = node.get(key)
        if isinstance(rows, list) and rows:
            bars: list[CandleExternalBar] = []
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                trade_date = to_date(row[0])
                open_price = to_float(row[1])
                close = to_float(row[2])
                high = to_float(row[3])
                low = to_float(row[4])
                if trade_date is None or open_price is None or close is None or high is None or low is None:
                    continue
                bars.append(
                    CandleExternalBar(
                        trade_date=trade_date,
                        open=open_price,
                        close=close,
                        high=high,
                        low=low,
                        volume=to_float(row[5]),
                    )
                )
            return bars
    return []


def parse_tencent_minutes(payload: dict[str, Any], symbol: str) -> MinuteExternalSeries:
    """把盘中的累计值换算成单分钟点.

    行的格式是 "HHMM price cumulative_volume cumulative_amount"。返回里还嵌着一份
    实时行情数组，昨收就从那里拿：分时线要以它为基准来画，而每次刷新都单独再问
    一次昨收要多花一个来回.
    """
    node = _tencent_node(payload, symbol)
    inner = node.get("data") if isinstance(node.get("data"), dict) else None
    if not isinstance(inner, dict):
        return MinuteExternalSeries()

    points = _minute_points(inner.get("data"), symbol)
    embedded = _tencent_quote_array(node.get("qt"), symbol)
    return MinuteExternalSeries(
        trade_date=to_date(inner.get("date")),
        prev_close=_field(embedded, 4),
        points=points,
    )


def _minute_points(rows: Any, symbol: str, trade_date: date | None = None) -> list[MinuteExternalPoint]:
    """把一个交易日的累计行转成单分钟点.

    累计值每个交易日都重新从头计，所以差分只在当天之内做；五日序列不过就是把
    五段这样的结果按从早到晚拼起来.
    """
    is_lot = symbol.startswith(("sh", "sz", "bj"))
    has_average = market_kind(symbol) == "stock"
    points: list[MinuteExternalPoint] = []
    previous_volume = 0.0
    previous_amount = 0.0
    for row in rows if isinstance(rows, list) else []:
        parts = str(row).split()
        if len(parts) < 4:
            continue
        price = to_float(parts[1])
        cumulative_volume = to_float(parts[2])
        cumulative_amount = to_float(parts[3])
        if price is None or cumulative_volume is None or cumulative_amount is None:
            continue
        stamp = parts[0].zfill(4)
        shares = cumulative_volume * (100 if is_lot else 1)
        points.append(
            MinuteExternalPoint(
                time=f"{stamp[0:2]}:{stamp[2:4]}",
                price=price,
                volume=max(cumulative_volume - previous_volume, 0.0),
                amount=max(cumulative_amount - previous_amount, 0.0),
                average_price=round(cumulative_amount / shares, 4) if shares > 0 and has_average else None,
                trade_date=trade_date,
            )
        )
        previous_volume, previous_amount = cumulative_volume, cumulative_amount
    return points


def parse_tencent_day_query(payload: dict[str, Any], symbol: str) -> MinuteExternalSeries:
    """五个交易日的分时数据，按从早到晚拼接.

    返回里的日期是新的在前，而且整段都没有基准昨收，所以调用方要从日线自己把
    `prev_close` 补上.
    """
    days = _tencent_node(payload, symbol).get("data")
    if not isinstance(days, list):
        return MinuteExternalSeries()

    sessions = sorted((day for day in days if isinstance(day, dict)), key=lambda day: str(day.get("date")))
    points: list[MinuteExternalPoint] = []
    for session in sessions:
        session_date = to_date(session.get("date"))
        points.extend(_minute_points(session.get("data"), symbol, trade_date=session_date))
    if not points:
        return MinuteExternalSeries()

    return MinuteExternalSeries(trade_date=to_date(sessions[-1].get("date")), points=points)


def _tencent_quote_array(qt: Any, symbol: str) -> list[str]:
    """K 线或分时返回里嵌着的那份行情数组.

    这个 dict 里还有空的资金流键和大盘状态条目，所以要先按代码名找，而不是随便
    拿第一个值.
    """
    if not isinstance(qt, dict):
        return []
    row = qt.get(symbol)
    if isinstance(row, list) and row:
        return row
    return next((value for value in qt.values() if isinstance(value, list) and value), [])


def normalize_company_rows(payload: dict[str, Any], symbol: str) -> CompanyExternalProfile | None:
    """摊平 A股 主数据的返回；其他市场没有等价的数据源."""
    rows = (payload.get("result") or {}).get("data") or []
    if not rows:
        return None
    row = rows[0]
    board = _pick(row, "BOARD_NAME_1LEVEL", "CSRC_INDUSTRY_NAME", "EM2016")
    concepts = _pick(row, "BLGAINIAN")
    return CompanyExternalProfile(
        symbol=symbol,
        name=_pick(row, "ORG_NAME", "SECURITY_NAME_ABBR"),
        industry=str(board).split("-")[-1] if board else None,
        region=_pick(row, "REGIONBK"),
        list_date=to_date(_pick(row, "LISTING_DATE")),
        main_business=_pick(row, "MAIN_BUSINESS"),
        description=_pick(row, "ORG_PROFILE"),
        employees=to_float(_pick(row, "TOTAL_NUM")),
        chairman=_pick(row, "CHAIRMAN"),
        concepts=[item for item in str(concepts).split(",") if item] if concepts else [],
    )


_SWEN_PREFIX = re.compile(r"^\d{1,3}(?=[\u4e00-\u9fff])")


def normalize_industry_rows(rows: list[dict[str, Any]], fund_code: str) -> list[FundExternalIndustry]:
    """只留最新一次披露的行业权重，按权重从大到小排.

    按年调一次会返回这一年已经公布的所有季度，得自己挑最新那期；行业名还带着
    申万指数的数字前缀（"50通信服务"），拿去和持仓表对照时那就是噪声.
    """
    parsed: list[tuple[date | None, str, float | None, float | None]] = []
    for row in rows:
        name = _pick(row, "行业类别", "行业", "industry")
        if name is None:
            continue
        parsed.append(
            (
                to_date(_pick(row, "截止时间", "截至时间", "date")),
                _SWEN_PREFIX.sub("", str(name).strip()),
                to_float(_pick(row, "占净值比例", "weight")),
                to_float(_pick(row, "市值", "market_value")),
            )
        )
    if not parsed:
        return []

    latest_as_of = max((as_of for as_of, *_rest in parsed if as_of is not None), default=None)
    industries = [
        FundExternalIndustry(
            fund_code=fund_code,
            industry=name,
            weight=weight,
            market_value=market_value,
            as_of=as_of,
        )
        for as_of, name, weight, market_value in parsed
        if (latest_as_of is None or as_of == latest_as_of) and weight
    ]
    industries.sort(key=lambda industry: industry.weight or 0.0, reverse=True)
    return industries
