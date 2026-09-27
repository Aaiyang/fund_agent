"""Market analysis endpoints: one listed instrument's quote, bars, minute line and profile.

Symbols are canonical listing codes (`sh600519`, `hk01810`, `usAAPL`, `sh000001`)
exactly as the holdings payload reports them. Validation happens in
`tencent_symbol`, which is the single whitelist every path through to the feed
goes by, so nothing here interpolates an unchecked string into an upstream URL.
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
    """Realtime snapshot: price, session range, turnover, valuation and caps."""
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
    """Adjusted OHLCV bars for the requested window."""
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
    """Minute line for one session, or for the last five stitched together.

    The response's `prev_close` is the reference the chart measures against.
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
    """Company master data. Empty for indexes and non-A股 listings."""
    company = await market_service.get_symbol_company(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail="symbol_not_found")
    return company
