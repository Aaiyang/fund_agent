"""账户（资产组合）API 端点."""

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
    """列出用户名下的账户，附带各自的导入状态."""
    items = await portfolio_service.list_accounts(identity.user_id)
    return AccountsResponse(items=items, total=len(items))


@router.post("", response_model=AccountItem, status_code=201)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["accounts"][0])
async def create_account(
    request: Request,
    payload: AccountCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AccountItem:
    """新建账户，账户名在该用户下必须尚未被占用."""
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
    """查询单个账户，含其最近一次导入状态."""
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
    """修改账户名称或来源标签."""
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
    """删除账户，并连带删除其持仓、流水与导入记录."""
    deleted = await portfolio_service.delete_account(identity.user_id, account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="account_not_found")
    return {"message": "deleted"}
