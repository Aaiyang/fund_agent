"""Portfolio API endpoints: summary, positions (optimistic lock), delete."""

from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.schemas.portfolio import (
    PortfolioSummaryResponse,
    PositionDeleteResponse,
    PositionItem,
    PositionUpsertRequest,
    PositionsResponse,
    TradeCreateRequest,
    TradePreviewResponse,
)
from app.analytics.positions import Operation
from app.services.portfolio_service import (
    AccountNotFoundError,
    NavNotPublishedError,
    PositionConflictError,
    TradeInputError,
    TradeTooLargeError,
    portfolio_service,
)

router = APIRouter()


@router.get("/summary", response_model=PortfolioSummaryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def get_portfolio_summary(
    request: Request,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PortfolioSummaryResponse:
    """Asset summary: total value, P/L, daily P/L, per-account list (spec 3.2)."""
    try:
        summary = await portfolio_service.get_summary(identity.user_id, account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    accounts = await portfolio_service.list_accounts(identity.user_id)
    return PortfolioSummaryResponse(summary=summary, accounts=accounts)


@router.get("/positions", response_model=PositionsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def list_positions(
    request: Request,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionsResponse:
    """List positions with derived metrics; optional account filter."""
    try:
        items = await portfolio_service.list_positions(identity.user_id, account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    return PositionsResponse(items=items, total=len(items))


@router.get("/positions/{fund_code}/trades/preview", response_model=TradePreviewResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def preview_trade(
    request: Request,
    fund_code: str,
    account_id: int = Query(gt=0),
    operation: Operation = Query(description="BUY / SELL / AUTO_INVEST / CONVERT"),
    trade_date: date = Query(description="提交订单的那天"),
    after_cutoff: bool = Query(default=False, description="是否 15:00 后提交"),
    amount: float | None = Query(default=None, gt=0),
    shares: float | None = Query(default=None, gt=0),
    fee: float | None = Query(default=None, ge=0),
    target_code: str | None = Query(default=None, min_length=6, max_length=6, description="转换目标基金"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> TradePreviewResponse:
    """Price an order on its confirm day and show the resulting holding.

    Declared before ``POST /positions/{fund_code}/trades`` in spirit but on a
    distinct path, so no literal segment can be swallowed by the fund code.
    """
    try:
        return await portfolio_service.preview_trade(
            identity.user_id,
            account_id,
            fund_code,
            operation,
            trade_date,
            after_cutoff,
            amount,
            shares,
            fee,
            target_code,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except NavNotPublishedError as e:
        raise HTTPException(status_code=409, detail="nav_not_published") from e
    except TradeInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/positions/{fund_code}/trades", response_model=PositionItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def record_trade(
    request: Request,
    fund_code: str,
    payload: TradeCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionItem:
    """Record a purchase or redemption and re-project the holding from the ledger."""
    try:
        return await portfolio_service.record_trade(
            identity.user_id,
            payload.account_id,
            fund_code,
            payload.operation,
            payload.trade_date,
            payload.after_cutoff,
            amount=payload.amount,
            shares=payload.shares,
            fee=payload.fee,
            target_code=payload.target_code,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except NavNotPublishedError as e:
        logger.info("trade_nav_not_published", user_id=identity.user_id, fund_code=e.fund_code)
        raise HTTPException(status_code=409, detail="nav_not_published") from e
    except TradeInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except TradeTooLargeError as e:
        raise HTTPException(status_code=422, detail=f"shares_exceed_holding:{e.held}") from e


@router.get("/positions/{fund_code}", response_model=PositionItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def get_position(
    request: Request,
    fund_code: str,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionItem:
    """One position; `account_id` narrows it to a single account (spec 9.3)."""
    try:
        if account_id is not None:
            position = await portfolio_service.get_position(identity.user_id, account_id, fund_code)
        else:
            positions = await portfolio_service.list_positions(identity.user_id, None)
            position = next((item for item in positions if item.fund_code == fund_code), None)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    if position is None:
        raise HTTPException(status_code=404, detail="position_not_found")
    return position


@router.patch("/positions/{fund_code}", response_model=PositionItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def upsert_position(
    request: Request,
    fund_code: str,
    payload: PositionUpsertRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionItem:
    """同步持仓: restate what the holdings screen shows (spec 3.7.1).

    Updates require `expected_version`; a stale version returns 409 so a
    concurrent screenshot import can never silently overwrite user edits. On a
    fund with a trade ledger, 份额/成本/收益 are dropped by the service — only
    持有金额 and 首次购买日期 come through this door.
    """
    try:
        return await portfolio_service.upsert_position(
            identity.user_id,
            payload.account_id,
            fund_code,
            expected_version=payload.expected_version,
            shares=payload.shares,
            market_value=payload.market_value,
            average_cost_nav=payload.average_cost_nav,
            purchase_date=payload.purchase_date,
            reset=payload.reset,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except PositionConflictError as e:
        logger.warning("position_version_conflict", user_id=identity.user_id, fund_code=fund_code)
        raise HTTPException(status_code=409, detail="position_version_conflict") from e


@router.delete("/positions/{fund_code}", response_model=PositionDeleteResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def delete_position(
    request: Request,
    fund_code: str,
    account_id: int,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionDeleteResponse:
    """Delete one position and write an audit adjustment record."""
    try:
        deleted = await portfolio_service.delete_position(identity.user_id, account_id, fund_code)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    if not deleted:
        raise HTTPException(status_code=404, detail="position_not_found")
    return PositionDeleteResponse(deleted=True)
