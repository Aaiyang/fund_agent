"""业绩比较基准指数序列，以及上市品种的分析行情.

指数收盘价存在 PostgreSQL，读取时按需回填；行情页每次访问都穿透抓取 ——
没人查询的行情就等于没人看过，
把这些行存下来只会让表里的数据慢慢跑偏。
"""

from datetime import date, timedelta
from typing import TypeVar

from pydantic import BaseModel

from app.analytics.returns import NavPoint, range_return
from app.core.cache import cache_key, cache_service
from app.core.logging import logger
from app.integrations.fund_data.akshare_provider import akshare_fund_provider
from app.integrations.fund_data.models import CandleExternalBar, MarketExternalQuote
from app.integrations.fund_data.normalizer import market_kind, tencent_symbol
from app.integrations.fund_data.tencent_client import (
    fetch_candles,
    fetch_company_profile,
    fetch_minutes,
    fetch_quotes,
    fetch_recent_minutes,
    resolve_symbol,
)
from app.repositories.index_repository import index_repository
from app.schemas.fund import NavRange
from app.schemas.market import (
    IndexCatalogItem,
    IndexHistoryResponse,
    IndexPoint,
    IndexQuoteItem,
    MarketPeriod,
    RealtimeIndexQuote,
    RealtimeMarketRequest,
    RealtimeMarketSnapshot,
    SymbolCompanyResponse,
    SymbolHistoryResponse,
    SymbolIntradayResponse,
    SymbolQuoteResponse,
)
from app.utils.clock import business_now, business_today, range_start, utc_now
from app.utils.market_quote_policy import MAINLAND_MARKET_TZ, clock_expects_updates, normalize_realtime_index

# 选择器用的固定目录。代码先在这里查，再决定是否访问 AKShare，
# 所以调用方可控的字符串永远不会传进第三方客户端。
# 顺序就是首页行情的顺序：两个大盘宽基指数排在最前。
BENCHMARK_INDEXES: dict[str, str] = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sz399006": "创业板指",
    "sh000012": "国债指数",
}

# 与收盘基准目录分开；全部代码均通过真实腾讯批量报价验证。
REALTIME_INDEXES: dict[str, str] = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sz399006": "创业板指",
    "sh000016": "上证50",
    "sh000905": "中证500",
    "sh000852": "中证1000",
    "sh000688": "科创50",
    "sz399673": "创业板50",
    "sz399005": "中小100",
    "sh000015": "红利指数",
    "sh000903": "中证A100",
    "sh000985": "中证全指",
    "bj899050": "北证50",
}
_REALTIME_INDEX_TTL_SECONDS = 15

# 每天只动一次的公开序列：每个指数在每个窗口内只抓一次数据源。
_SYNC_TTL_SECONDS = 6 * 3600
_STALE_DAYS = 3
# 留得足够长，即使遇上连休也能拿到两个交易日的收盘。
_QUOTE_LOOKBACK_DAYS = 20

# 行情页各块数据值得隔多久重新抓一次。K线一天只动一次，
# 快照和分时线则整个盘中都在动。
_SYMBOL_QUOTE_TTL_SECONDS = 30
_SYMBOL_INTRADAY_TTL_SECONDS = 60
_SYMBOL_HISTORY_TTL_SECONDS = 600
_COMPANY_TTL_SECONDS = 24 * 3600
# 每个命名区间大致包含多少个交易日，用来决定 K线要请求多少根。
_TRADING_DAYS: dict[str, int] = {"1m": 22, "3m": 63, "6m": 126, "1y": 250, "3y": 750, "all": 1200}
# 每个周期的每根 K线代表多少个交易日。
_TRADING_DAYS_PER_BAR: dict[MarketPeriod, int] = {"day": 1, "week": 5, "month": 21}
# 找五日窗口起点之前那个收盘价时，要拉多少根日线：
# 往回七个自然日最多也就几个交易日，把节假日也算进去了。
_BASELINE_BARS = 15

ModelT = TypeVar("ModelT", bound=BaseModel)


class MarketService:
    """读取基准指数收盘价，已存的数据不够时按需从数据源补齐."""

    def catalog(self) -> list[IndexCatalogItem]:
        """可供选择的业绩比较基准，按选择器里的顺序."""
        return [IndexCatalogItem(index_code=code, name=name) for code, name in BENCHMARK_INDEXES.items()]

    async def get_realtime_quotes(self, request: RealtimeMarketRequest) -> RealtimeMarketSnapshot | None:
        """批量查询主要指数，默认在线刷新；只缓存完整成功结果，不回退日线."""
        codes = list(dict.fromkeys(request.index_codes or REALTIME_INDEXES))
        # 服务层再次白名单校验，构造请求和读取缓存之前拒绝任意 URL / 个股。
        if any(code not in REALTIME_INDEXES for code in codes):
            raise ValueError("仅支持主要A股指数目录中的代码")
        key = cache_key("market_realtime_indexes:v1", *sorted(codes))
        cached = None
        if not request.refresh:
            try:
                raw = await cache_service.get(key)
                if raw:
                    cached = RealtimeMarketSnapshot.model_validate_json(raw)
            except Exception:
                logger.exception("market_realtime_cache_read_failed")

        now = business_now().astimezone(MAINLAND_MARKET_TZ)
        if cached is not None:
            age = (utc_now() - cached.fetched_at).total_seconds() if cached.fetched_at.tzinfo is None else float("inf")
            if not (
                0 <= age < _REALTIME_INDEX_TTL_SECONDS
                and cached.requested_date == now.date()
                and not cached.stale
                and not cached.missing_indexes
                and {item.index_code for item in cached.indexes} == set(codes)
            ):
                cached = None
        if cached is None:
            quotes = await fetch_quotes(codes)
            fetched_at = utc_now()
        else:
            # 即使跨越了午休/开盘边界，也重新核对每只指数的时效。
            quotes = [
                MarketExternalQuote(
                    **item.model_dump(exclude={"index_code", "trade_date", "freshness", "stale", "quote_time"}),
                    symbol=item.index_code,
                    kind="index",
                    quote_time=item.quote_time.isoformat() if item.quote_time else None,
                )
                for item in cached.indexes
            ]
            fetched_at = cached.fetched_at

        # 获取完成后再判断新鲜度，避免请求期间跨越业务日期。
        now = business_now().astimezone(MAINLAND_MARKET_TZ)
        by_symbol = {quote.symbol: quote for quote in quotes if quote.symbol in codes}
        indexes: list[RealtimeIndexQuote] = []
        missing: list[IndexCatalogItem] = []
        for code in codes:
            quote = by_symbol.get(code)
            item = normalize_realtime_index(quote, REALTIME_INDEXES[code], now) if quote else None
            if item is None:
                missing.append(IndexCatalogItem(index_code=code, name=REALTIME_INDEXES[code]))
            else:
                indexes.append(item)
        if not indexes:
            logger.warning("market_realtime_quotes_empty", requested=len(codes))
            return None

        warnings = [
            "公开行情快照可能延迟，实际交易日未核验；请按每只指数的 quote_time 判断，不保证交易所级实时性。",
            "指数成分可能重叠，各指数成交额不能相加当作全市场成交额；也不代表个股涨跌家数或资金流向。",
        ]
        if not clock_expects_updates(now):
            warnings.append("当前按时钟处于盘前、午间、收盘后或周末，返回最近可用报价；实际交易日未核验。")
        if missing:
            warnings.append("部分指数未返回有效点位：" + "、".join(item.name for item in missing))
        stale = any(item.stale for item in indexes)
        if stale:
            warnings.append("部分报价不是今日数据、盘中可能延迟或时间不可核验；不能称为今日实时行情。")
        if any(item.change_pct is None for item in indexes):
            warnings.append("部分指数缺少涨跌幅，不可把缺失值当作零。")
        response = RealtimeMarketSnapshot(
            requested_date=now.date(),
            fetched_at=fetched_at,
            from_cache=cached is not None,
            indexes=indexes,
            missing_indexes=missing,
            stale=stale,
            warnings=warnings,
        )
        if cached is None and not stale and not missing and all(item.change_pct is not None for item in indexes):
            try:
                await cache_service.set(key, response.model_dump_json(), ttl=_REALTIME_INDEX_TTL_SECONDS)
            except Exception:
                logger.exception("market_realtime_cache_write_failed")
        logger.info("market_realtime_quotes_ready", requested=len(codes), returned=len(indexes), stale=stale)
        return response

    async def get_history(self, index_code: str, range_key: NavRange) -> IndexHistoryResponse | None:
        """某个基准的收盘价序列，以及该区间内的累计涨跌幅.

        Returns:
            序列数据；`index_code` 不是已知的基准时返回 None。
        """
        name = BENCHMARK_INDEXES.get(index_code)
        if name is None:
            logger.info("index_unknown_code", index_code=index_code)
            return None

        today = business_today()
        start = range_start(range_key, today)
        await self._ensure_stored(index_code, start, today)
        rows = await index_repository.get_history(index_code, start, today)
        points = [IndexPoint(trade_date=row.trade_date, close=row.close) for row in rows]
        return IndexHistoryResponse(
            index_code=index_code,
            name=name,
            range=range_key,
            points=points,
            period_return=_window_change(points),
        )

    async def get_quotes(self) -> list[IndexQuoteItem]:
        """目录里每个指数的最新收盘价和当日涨跌，按选择器顺序返回.

        行情是公开数据，没有任何按用户的部分，
        所以用图表读的那份落库序列来供也无妨；
        某个指数没缓存，就在这里多付一次抓取，跟基金页一样。
        """
        today = business_today()
        start = today - timedelta(days=_QUOTE_LOOKBACK_DAYS)
        quotes: list[IndexQuoteItem] = []
        for code, name in BENCHMARK_INDEXES.items():
            await self._ensure_stored(code, start, today)
            rows = await index_repository.get_history(code, start, today)
            closes = [row.close for row in rows if row.close is not None]
            quotes.append(
                IndexQuoteItem(
                    index_code=code,
                    name=name,
                    close=closes[-1] if closes else None,
                    change_pct=_daily_change(closes),
                    trade_date=rows[-1].trade_date if rows else None,
                )
            )
        return quotes

    async def get_symbol_quote(self, symbol: str) -> SymbolQuoteResponse | None:
        """单个上市品种的行情快照；代码不可用时返回 None.

        代码在进数据源之前会先按格式白名单归一化，
        所以未经校验的字符串绝不会被拼进请求里。
        """
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_quote", canonical)
        cached = await _read_cache(key, SymbolQuoteResponse)
        if cached is not None:
            return cached

        quotes = await fetch_quotes([canonical])
        if not quotes:
            logger.warning("market_quote_empty", symbol=canonical)
            return None

        response = SymbolQuoteResponse.model_validate(quotes[0].model_dump())
        await _write_cache(key, response, _SYMBOL_QUOTE_TTL_SECONDS)
        return response

    async def get_symbol_history(
        self, symbol: str, period: MarketPeriod, range_key: NavRange
    ) -> SymbolHistoryResponse | None:
        """单个品种复权后的 K线，按请求的区间裁剪."""
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_history", canonical, period, range_key)
        cached = await _read_cache(key, SymbolHistoryResponse)
        if cached is not None:
            return cached

        bars = await fetch_candles(await resolve_symbol(canonical), period, _bar_count(period, range_key))
        if not bars:
            logger.warning("market_history_empty", symbol=canonical, period=period)
            return None

        start = range_start(range_key, business_today())
        window = [bar for bar in bars if start is None or bar.trade_date >= start]
        response = SymbolHistoryResponse(
            symbol=canonical,
            kind=market_kind(canonical),
            period=period,
            range=range_key,
            bars=window,
            total=len(window),
            period_return=_bars_change(window),
        )
        await _write_cache(key, response, _SYMBOL_HISTORY_TTL_SECONDS)
        return response

    async def get_symbol_intraday(self, symbol: str, five_day: bool = False) -> SymbolIntradayResponse | None:
        """本日的分时线，或者把最近五日拼在一起的分时线.

        数据源没有历史的那些市场，非交易时段返回空。
        """
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_intraday", canonical, "5" if five_day else "1")
        cached = await _read_cache(key, SymbolIntradayResponse)
        if cached is not None:
            return cached

        series = await (fetch_recent_minutes(canonical) if five_day else fetch_minutes(canonical))
        if not series.points:
            logger.info("market_intraday_empty", symbol=canonical, five_day=five_day)
            return None

        response = SymbolIntradayResponse(
            symbol=canonical,
            kind=market_kind(canonical),
            days=5 if five_day else 1,
            trade_date=series.trade_date,
            prev_close=series.prev_close
            if not five_day
            else await self._close_before(canonical, series.points[0].trade_date),
            points=series.points,
            total=len(series.points),
        )
        await _write_cache(key, response, _SYMBOL_INTRADAY_TTL_SECONDS)
        return response

    async def _close_before(self, symbol: str, day: date | None) -> float | None:
        """`day` 之前最后一个交易日的收盘价，五日图正是拿它当基准.

        五日的回复本身不带基准值。取不到也不算错误：
        这时图表改成按数据自身缩放，
        而不是画一条平直的基准线。
        """
        if day is None:
            return None
        try:
            bars = await fetch_candles(await resolve_symbol(symbol), "day", _BASELINE_BARS)
        except Exception as e:
            logger.warning("market_baseline_fetch_failed", symbol=symbol, error=str(e))
            return None
        earlier = [bar.close for bar in bars if bar.trade_date < day]
        return earlier[-1] if earlier else None

    async def get_symbol_company(self, symbol: str) -> SymbolCompanyResponse | None:
        """公司主数据。查不到只是把这张卡片藏起来，不是错误.

        这一块是唯一来自东方财富而不是行情数据源的，
        而从这里访问它是时断时续的，所以失败只记日志、
        按"没有资料"返回，不连带把图表一起弄挂。
        """
        canonical = tencent_symbol(symbol)
        if canonical is None:
            logger.info("market_symbol_rejected", symbol=symbol)
            return None

        key = ("market_company", canonical)
        cached = await _read_cache(key, SymbolCompanyResponse)
        if cached is not None:
            return cached

        try:
            company = await fetch_company_profile(canonical)
        except Exception as e:
            logger.warning("market_company_fetch_failed", symbol=canonical, error=str(e))
            company = None

        response = SymbolCompanyResponse(symbol=canonical, company=company)
        # 只有真正查到的记录才值得留着；没查到的下次要重试。
        if company is not None:
            await _write_cache(key, response, _COMPANY_TTL_SECONDS)
        return response

    async def _ensure_stored(self, index_code: str, start: date | None, today: date) -> None:
        """已存的数据撑不起请求区间时，拉一次完整的日线序列."""
        coverage = await index_repository.get_coverage(index_code)
        if coverage is not None and _covers(coverage, start, today):
            return
        lock_key = cache_key("index_sync", index_code)
        if not await cache_service.acquire_lock(lock_key, ttl=_SYNC_TTL_SECONDS):
            return

        try:
            quotes = await akshare_fund_provider.get_index_history(index_code)
            if quotes:
                await index_repository.upsert_quotes(quotes)
                logger.info("index_history_synced", index_code=index_code, rows=len(quotes))
            else:
                logger.warning("index_history_empty", index_code=index_code)
        except Exception as e:
            # 基准数据源出问题不能把一次读请求变成 500：
            # 库里有什么就先给什么，把重试留给下一个请求。
            logger.warning("index_history_sync_failed", index_code=index_code, error=str(e))
            await cache_service.release_lock(lock_key)


def _daily_change(closes: list[float]) -> float | None:
    """最近两个交易日收盘之间的涨跌幅，单位是百分点."""
    if len(closes) < 2 or not closes[-2]:
        return None
    return round((closes[-1] - closes[-2]) / closes[-2] * 100, 4)


def _bar_count(period: MarketPeriod, range_key: NavRange) -> int:
    """请求多少根 K线：既覆盖住整个区间，又不至于多取十年的数据."""
    per_bar = _TRADING_DAYS_PER_BAR[period]
    days = _TRADING_DAYS[range_key]
    return days if per_bar == 1 else max(days // per_bar, 6)


def _bars_change(bars: list[CandleExternalBar]) -> float | None:
    """跨返回的这些 K线，收盘对收盘的累计涨跌幅."""
    return _window_change([IndexPoint(trade_date=bar.trade_date, close=bar.close) for bar in bars])


async def _read_cache(key_parts: tuple[str, ...], model: type[ModelT]) -> ModelT | None:
    """读出缓存里的响应；记录读坏了就当作未命中."""
    raw = await cache_service.get(cache_key(*key_parts))
    if not raw:
        return None
    try:
        return model.model_validate_json(raw)
    except ValueError:
        logger.warning("market_cache_invalid", key=key_parts[0])
        return None


async def _write_cache(key_parts: tuple[str, ...], model: BaseModel, ttl: int) -> None:
    await cache_service.set(cache_key(*key_parts), model.model_dump_json(), ttl=ttl)


def _covers(coverage: tuple[date, date], start: date | None, today: date) -> bool:
    """落库序列覆盖了请求区间、而且还不算陈旧时返回 True."""
    earliest, latest = coverage
    if start is not None and earliest > start:
        return False
    return latest >= today - timedelta(days=_STALE_DAYS)


def _window_change(points: list[IndexPoint]) -> float | None:
    """返回区间内收盘对收盘的累计涨跌幅."""
    if len(points) < 2:
        return None
    series = [NavPoint(date=point.trade_date, nav=point.close) for point in points]
    return range_return(series, series[0].date, series[-1].date)


market_service = MarketService()
