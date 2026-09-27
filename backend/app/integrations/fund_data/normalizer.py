"""Normalizers converting raw AKShare payloads into internal domain models.

All parsing is defensive: third-party column names and value formats change
between AKShare versions, so every field is optional and every cast tolerant.
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
    """Cast a raw cell (number, numeric string, '1.23%', '--') to float."""
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
    """Cast a raw date cell (date, datetime, 'YYYY-MM-DD', 'YYYYMMDD') to date.

    Anything unparseable becomes None: pandas hands us NaT for missing dates,
    and touching a NaT raises rather than returning None.
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


# Sentinels AKShare/pandas use for "no value"; NaT reaches us as a str() of 'NaT'
# and NaN as a float that is not equal to itself.
_MISSING_TOKENS = {"", "--", "-", "—", "None", "nan", "NaN", "NaT", "nat"}


def _is_missing(value: Any) -> bool:
    """True for None, NaN, NaT and the placeholder strings AKShare emits."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    if str(value).strip() in _MISSING_TOKENS:
        return True
    # pandas NaT is datetime-like but explodes on any real use
    return type(value).__name__ == "NaTType"


def _pick(record: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value among candidate column names."""
    for key in keys:
        value = record.get(key)
        if not _is_missing(value):
            return value
    return None


def normalize_fund_record(record: dict[str, Any]) -> FundExternalRecord | None:
    """Normalize one search/rank row into a FundExternalRecord."""
    fund_code = _pick(record, "基金代码", "fund_code", "代码")
    fund_name = _pick(record, "基金简称", "基金全称", "fund_name", "名称")
    if not fund_code:
        return None
    return FundExternalRecord(
        fund_code=str(fund_code).strip().zfill(6),
        fund_name=str(fund_name or "").strip(),
        fund_type=str(_pick(record, "基金类型", "fund_type")).strip() or None if _pick(record, "基金类型") else None,
        latest_nav=to_float(_pick(record, "单位净值", "最新净值", "nav")),
        nav_date=to_date(_pick(record, "日期", "净值日期", "nav_date")),
        daily_return=to_float(_pick(record, "日增长率", "日涨跌幅", "daily_return")),
    )


def _text(info: dict[str, Any], limit: int, *keys: str) -> str | None:
    """First usable value among the candidate keys, trimmed to `limit` characters."""
    value = _pick(info, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def normalize_profile_rows(rows: list[dict[str, Any]], fund_code: str) -> FundExternalProfile | None:
    """Normalize fund_individual_basic_info_xq-style item/value rows."""
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

    # AKShare renamed this cell across versions: 成立日期 / 成立日期/规模 / 成立时间
    # all appear in the wild, and a missed key silently yields None.
    inception_raw = _pick(info, "成立日期", "成立日期/规模", "成立时间", "发行日期")
    inception = None
    if inception_raw:
        text = str(inception_raw).strip()
        # "2021-01-01/2.34亿" carries the size after the date; slash-formatted
        # dates must not be split, so the whole value is tried first.
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
    """Merge unit-NAV and accumulated-NAV rows keyed by NAV date."""
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
    """Convert an index daily frame into ascending (date, close) quotes.

    AKShare's index endpoints disagree on column naming between versions and
    sources (Sina is lowercase English, Eastmoney is Chinese), so both
    spellings are accepted and unusable rows are dropped.
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
    """Order key for a reporting period like ``2026年2季度股票投资明细``."""
    if label is None:
        return None
    match = _QUARTER_PATTERN.search(str(label))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def normalize_holding_rows(rows: list[dict[str, Any]], fund_code: str) -> list[FundExternalHolding]:
    """Convert ``fund_portfolio_hold_em`` rows into holdings with their quarter."""
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
    """Map a holding's code to its quote symbol; markets are encoded in the shape.

    The holdings table carries no market column, so a 6-digit code is a Chinese
    listing (5/6/9 Shanghai, otherwise Shenzhen), a 5-digit one is Hong Kong, and
    a lettered ticker is a US listing.
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
    """Parse the batched quote reply; each market has its own field layout."""
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

_INDEX_SYMBOL_PREFIXES = ("sh000", "sz399")

_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _tencent_node(payload: Any, symbol: str) -> dict[str, Any]:
    """One instrument's object inside a market reply.

    The feed reports "no data" as a bare ``"data": []`` rather than an empty
    object, so every level has to be type-checked before it is indexed.
    """
    container = payload.get("data") if isinstance(payload, dict) else None
    node = container.get(symbol) if isinstance(container, dict) else None
    return node if isinstance(node, dict) else {}


def market_kind(symbol: str) -> str:
    """Index or stock, from the symbol shape; no listing table carries a market column.

    ``sh000*`` and ``sz399*`` are the Shanghai and Shenzhen index ranges. The
    overlap is deliberate: ``sh000001`` is 上证指数 while ``sz000001`` is 平安银行.
    """
    return "index" if symbol.startswith(_INDEX_SYMBOL_PREFIXES) else "stock"


def tencent_symbol(stock_code: str) -> str | None:
    """Map a listing code to Tencent's symbol form.

    Same shape-based market inference as :func:`sina_symbol`, except US tickers
    keep their upper case because the feed is case-sensitive there, and an
    already prefixed symbol passes through so callers can round-trip it.
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
    """Normalize the two timestamp shapes the feed uses per market."""
    value = raw.strip()
    if re.fullmatch(r"\d{14}", value):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"
    return value or None


def _field(fields: list[str], index: int) -> float | None:
    return to_float(fields[index]) if index < len(fields) else None


def parse_tencent_quotes(payload: str) -> list[MarketExternalQuote]:
    """Parse the batched snapshot reply; the field layout varies per market.

    Offsets 1-45 line up across A股, 港股, 美股 and 指数. Beyond that the layouts
    diverge, so the extras are read through the per-market helpers below rather
    than a single index table. 五档买卖盘 is deliberately not parsed: it is only
    populated during a session and no screen shows it.
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
                # A股 and 指数 pack "price/volume/amount" into 35 with amount in 元;
                # 港股 and 美股 leave a bare price there and report 元 at 37.
                amount=_field(base, 2) if len(base) == 3 else _field(fields, 37),
                # 港股 leaves 换手率 at a literal 0 and a halted stock reports 0 too;
                # neither is worth rendering, so both become missing.
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
    """市净率 sits at 46 for A股; other markets put the English name there."""
    return _field(fields, 46) if len(fields) > 80 else None


def _quote_week52(fields: list[str]) -> tuple[float | None, float | None]:
    """A股 reports 52-week extremes at 67/68, 港股 and 美股 at 48/49."""
    if len(fields) > 80:
        return _field(fields, 67), _field(fields, 68)
    return _field(fields, 48), _field(fields, 49)


def parse_tencent_candles(payload: dict[str, Any], symbol: str) -> list[CandleExternalBar]:
    """Read one instrument's bar array out of the K-line reply.

    The row order is date, open, **close, high**, low, volume — not OHLC. A
    Hong Kong row may carry a trailing corporate-action dict, which is why the
    slice is positional from the left rather than "everything but the last".
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
    """Convert the session's running totals into per-minute points.

    Rows are "HHMM price cumulative_volume cumulative_amount". The reply also
    embeds the live quote array, which is where the previous close comes from:
    the minute line is plotted against it, and asking for it separately would
    cost a second round trip on every refresh.
    """
    node = _tencent_node(payload, symbol)
    inner = node.get("data") if isinstance(node.get("data"), dict) else None
    if not isinstance(inner, dict):
        return MinuteExternalSeries()

    rows = inner.get("data")
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
            )
        )
        previous_volume, previous_amount = cumulative_volume, cumulative_amount

    embedded = _tencent_quote_array(node.get("qt"), symbol)
    return MinuteExternalSeries(
        trade_date=to_date(inner.get("date")),
        prev_close=_field(embedded, 4),
        points=points,
    )


def _tencent_quote_array(qt: Any, symbol: str) -> list[str]:
    """The quote array embedded in a K-line or minute reply.

    The dict also carries an empty money-flow key and a market-status entry, so
    the symbol is looked up by name rather than taking the first value.
    """
    if not isinstance(qt, dict):
        return []
    row = qt.get(symbol)
    if isinstance(row, list) and row:
        return row
    return next((value for value in qt.values() if isinstance(value, list) and value), [])


def normalize_company_rows(payload: dict[str, Any], symbol: str) -> CompanyExternalProfile | None:
    """Flatten the A股 master-data reply; other markets have no equivalent source."""
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
    """Keep the newest disclosure's industry weights, heaviest first.

    One yearly call returns every quarter published so far, and the industry
    names come with their Shenwan index prefix ("50通信服务"), which is noise to
    a reader comparing it against the holdings table.
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
