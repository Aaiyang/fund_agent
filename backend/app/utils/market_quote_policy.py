"""主要 A 股指数报价的时间核验，不把旧报价或时钟推测标成实时开市."""

from datetime import datetime, time, timedelta
from math import isfinite
import re
from zoneinfo import ZoneInfo

from app.integrations.fund_data.models import MarketExternalQuote
from app.schemas.market import RealtimeIndexQuote, RealtimeQuoteFreshness

MAINLAND_MARKET_TZ = ZoneInfo("Asia/Shanghai")
MAX_INTRADAY_QUOTE_AGE_SECONDS = 180


def finite_number(value: float | None) -> float | None:
    """异常数值是未知，不让 NaN / Inf 混入行情 JSON."""
    return value if value is not None and isfinite(value) else None


def clock_expects_updates(now: datetime) -> bool:
    """仅按上海星期和时间估算连续交易时段，不核验交易所日历."""
    moment = now.astimezone(MAINLAND_MARKET_TZ)
    current = moment.time()
    return moment.weekday() < 5 and (time(9, 30) <= current < time(11, 30) or time(13) <= current < time(15))


def normalize_realtime_index(quote: MarketExternalQuote, name: str, now: datetime) -> RealtimeIndexQuote | None:
    """使用真实报价时间判断新旧，缺时间时保留数值但明确无法确认新鲜度."""
    price = finite_number(quote.price)
    if price is None or price <= 0:
        return None
    moment = now.astimezone(MAINLAND_MARKET_TZ)
    quote_time = None
    if quote.quote_time and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?", quote.quote_time
    ):
        try:
            # 本工具只查大陆指数；上游不带偏移的时间明确按上海解释。
            quote_time = datetime.fromisoformat(quote.quote_time)
            if quote_time.tzinfo is None:
                quote_time = quote_time.replace(tzinfo=MAINLAND_MARKET_TZ)
            quote_time = quote_time.astimezone(MAINLAND_MARKET_TZ)
        except ValueError:
            quote_time = None

    freshness: RealtimeQuoteFreshness = "same_day"
    stale = False
    if quote_time is None:
        freshness, stale = "unknown_time", True
    elif quote_time.date() > moment.date() or quote_time > moment + timedelta(seconds=60):
        freshness, stale = "future_time", True
    elif quote_time.date() != moment.date():
        freshness, stale = "previous_session", True
    else:
        # 午休和收盘后以本段结束时刻为参照，不因报价正常停更就误标延迟；
        # 也不能让上午旧报价在下午收盘后变成“新鲜”。仅是时钟核验，非开市证明。
        reference = None
        current = moment.time()
        if moment.weekday() < 5:
            if clock_expects_updates(moment):
                reference = moment
            elif time(11, 30) <= current < time(13):
                reference = moment.replace(hour=11, minute=30, second=0, microsecond=0)
            elif current >= time(15):
                reference = moment.replace(hour=15, minute=0, second=0, microsecond=0)
        if reference and (reference - quote_time).total_seconds() > MAX_INTRADAY_QUOTE_AGE_SECONDS:
            freshness, stale = "delayed", True

    return RealtimeIndexQuote(
        index_code=quote.symbol,
        name=name,
        price=price,
        change=finite_number(quote.change),
        change_pct=finite_number(quote.change_pct),
        prev_close=finite_number(quote.prev_close),
        open=finite_number(quote.open),
        high=finite_number(quote.high),
        low=finite_number(quote.low),
        amount=finite_number(quote.amount),
        quote_time=quote_time,
        trade_date=quote_time.date() if quote_time else None,
        freshness=freshness,
        stale=stale,
    )
