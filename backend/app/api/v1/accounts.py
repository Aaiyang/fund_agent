"""Accounts API endpoints."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.portfolio import (
    AccountCreateRequest,
    AccountItem,
    AccountUpdateRequest,
    AccountsResponse,
)
from app.services.portfolio_service import AccountNameConflictError, portfolio_service

router = APIRouter()

NAME_TAKEN_DETAIL = "account_name_taken"


@router.get("", response_model=AccountsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["accounts"][0])
async def list_accounts(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AccountsResponse:
    """List the user's portfolio accounts with import status."""
    items = await portfolio_service.list_accounts(identity.user_id)
    return AccountsResponse(items=items, total=len(items))


@router.post("", response_model=AccountItem, status_code=201)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["accounts"][0])
async def create_account(
    request: Request,
    payload: AccountCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AccountItem:
    """Create a portfolio account; the name must be new for this user."""
    try:
        return await portfolio_service.create_account(
            identity.user_id, payload.name, payload.source_app, payload.account_type, payload.import_mode
        )
    except AccountNameConflictError as error:
        raise HTTPException(status_code=409, detail=NAME_TAKEN_DETAIL) from error


@router.get("/{account_id}", response_model=AccountItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["accounts"][0])
async def get_account(
    request: Request,
    account_id: int,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AccountItem:
    """Get one account with its latest import status."""
    accounts = await portfolio_service.list_accounts(identity.user_id)
    for account in accounts:
        if account.id == account_id:
            return account
    raise HTTPException(status_code=404, detail="account_not_found")


@router.patch("/{account_id}", response_model=AccountItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["accounts"][0])
async def update_account(
    request: Request,
    account_id: int,
    payload: AccountUpdateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AccountItem:
    """Rename an account or change its source label."""
    try:
        updated = await portfolio_service.update_account(
            identity.user_id, account_id, payload.name, payload.source_app
        )
    except AccountNameConflictError as error:
        raise HTTPException(status_code=409, detail=NAME_TAKEN_DETAIL) from error
    if updated is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    return updated


@router.delete("/{account_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["accounts"][0])
async def delete_account(
    request: Request,
    account_id: int,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    """Delete an account and its positions / transactions / import records."""
    deleted = await portfolio_service.delete_account(identity.user_id, account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="account_not_found")
    return {"message": "deleted"}
