"""行情分析端点：单只上市标的的实时报价、K 线、分时线与公司资料.

symbol 用规范化的上市代码（`sh600519`、`hk01810`、`usAAPL`、`sh000001`），
与持仓数据上报的写法完全一致。校验全部收在 `tencent_symbol` 里，它是通往
上游取数路径上唯一的白名单，因此这里不会把没校验过的字符串拼进上游 URL。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.fund import NavRange
from app.schemas.market import (
    MarketPeriod,
    SymbolCompanyResponse,
    SymbolHistoryResponse,
    SymbolIntradayResponse,
    SymbolQuoteResponse,
)
from app.services.market_service import market_service

router = APIRouter()


@router.get("/{symbol}/quote", response_model=SymbolQuoteResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["markets"][0])
async def get_symbol_quote(
    request: Request,
    symbol: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> SymbolQuoteResponse:
    """实时快照：现价、当日高低区间、成交额、估值与市值."""
    quote = await market_service.get_symbol_quote(symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail="symbol_not_found")
    return quote


@router.get("/{symbol}/history", response_model=SymbolHistoryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["markets"][0])
async def get_symbol_history(
    request: Request,
    symbol: str,
    range: NavRange = Query(default="1y", description="图表区间：1m/3m/6m/1y/3y/all"),
    period: MarketPeriod = Query(default="day", description="K线周期：day/week"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> SymbolHistoryResponse:
    """返回请求区间的复权 OHLCV K 线."""
    history = await market_service.get_symbol_history(symbol, period, range)
    if history is None:
        raise HTTPException(status_code=404, detail="symbol_not_found")
    return history


@router.get("/{symbol}/intraday", response_model=SymbolIntradayResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["markets"][0])
async def get_symbol_intraday(
    request: Request,
    symbol: str,
    days: int = Query(default=1, description="分钟线覆盖的交易日数：1 或 5"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> SymbolIntradayResponse:
    """返回单个交易日的分时线，或把最近 5 个交易日拼接起来.

    响应里的 `prev_close` 就是图表计算涨跌所参照的前收盘价。
    """
    if days not in (1, 5):
        raise HTTPException(status_code=422, detail="days_must_be_1_or_5")
    intraday = await market_service.get_symbol_intraday(symbol, days == 5)
    if intraday is None:
        raise HTTPException(status_code=404, detail="intraday_unavailable")
    return intraday


@router.get("/{symbol}/company", response_model=SymbolCompanyResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["markets"][0])
async def get_symbol_company(
    request: Request,
    symbol: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> SymbolCompanyResponse:
    """上市公司主数据；指数和 A 股以外的标的返回空."""
    company = await market_service.get_symbol_company(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail="symbol_not_found")
    return company
