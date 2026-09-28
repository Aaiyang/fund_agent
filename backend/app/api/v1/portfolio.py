"""Portfolio API endpoints: summary, positions (optimistic lock), delete."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
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
)
from app.services.portfolio_service import AccountNotFoundError, PositionConflictError, portfolio_service

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
    """Create or update a position snapshot (manual entry, spec 3.7.1).

    Updates require `expected_version`; a stale version returns 409 so a
    concurrent screenshot import can never silently overwrite user edits.
    """
    try:
        return await portfolio_service.upsert_position(
            identity.user_id,
            payload.account_id,
            fund_code,
            expected_version=payload.expected_version,
            shares=payload.shares,
            cost_amount=payload.cost_amount,
            average_cost_nav=payload.average_cost_nav,
            market_value=payload.market_value,
            profit_loss=payload.profit_loss,
            purchase_date=payload.purchase_date,
            purchase_after_cutoff=payload.purchase_after_cutoff,
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
