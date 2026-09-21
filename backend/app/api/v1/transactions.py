"""Transactions API endpoints (read-only view of records/adjustments)."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.portfolio import TransactionsResponse
from app.services.portfolio_service import AccountNotFoundError, portfolio_service

router = APIRouter()


@router.get("", response_model=TransactionsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["transactions"][0])
async def list_transactions(
    request: Request,
    account_id: int | None = None,
    fund_code: str | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> TransactionsResponse:
    """List transactions/adjustments, newest first (spec 3.8)."""
    try:
        items = await portfolio_service.list_transactions(identity.user_id, account_id, fund_code)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    return TransactionsResponse(items=items, total=len(items))
