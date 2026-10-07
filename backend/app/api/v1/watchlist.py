"""自选 API 端点：自选基金的查询、加入、移除与分组 CRUD.

路由顺序不能随意改：静态的 ``/groups`` 必须注册在动态的 ``/{fund_code}`` 之前，
否则 "groups" 会被当成基金代码捕获。
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistGroupCreateRequest,
    WatchlistGroupItem,
    WatchlistGroupUpdateRequest,
    WatchlistGroupsResponse,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from app.services.watchlist_service import watchlist_service

router = APIRouter()


# ---------------------------------------------------------------------------
# 分组相关（静态路径先注册）
# ---------------------------------------------------------------------------


@router.get("/groups", response_model=WatchlistGroupsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def list_groups(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistGroupsResponse:
    """列出用户的自选分组."""
    items = await watchlist_service.list_groups(identity.user_id)
    return WatchlistGroupsResponse(items=items, total=len(items))


@router.post("/groups", response_model=WatchlistGroupItem, status_code=201)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def create_group(
    request: Request,
    payload: WatchlistGroupCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistGroupItem:
    """新建一个自定义自选分组."""
    return await watchlist_service.create_group(identity.user_id, payload.name, payload.sort_order)


@router.patch("/groups/{group_id}", response_model=WatchlistGroupItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def update_group(
    request: Request,
    group_id: int,
    payload: WatchlistGroupUpdateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistGroupItem:
    """改分组名、调排序，或整份重写组内成员."""
    updated = await watchlist_service.update_group(
        identity.user_id, group_id, payload.name, payload.sort_order, payload.fund_codes
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="group_not_found")
    return updated


@router.delete("/groups/{group_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def delete_group(
    request: Request,
    group_id: int,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    """删除分组；组里的基金仍然留在自选里."""
    deleted = await watchlist_service.delete_group(identity.user_id, group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="group_not_found")
    return {"message": "deleted"}


# ---------------------------------------------------------------------------
# 自选基金
# ---------------------------------------------------------------------------


@router.get("", response_model=WatchlistResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist"][0])
async def list_watchlist(
    request: Request,
    group_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistResponse:
    """列出自选基金，附最新净值与当日涨跌."""
    items = await watchlist_service.list_funds(identity.user_id, group_id=group_id)
    return WatchlistResponse(items=items, total=len(items))


@router.post("", response_model=WatchlistResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist"][0])
async def add_to_watchlist(
    request: Request,
    payload: WatchlistAddRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistResponse:
    """把基金加进自选（基金代码查不到时返回 404）."""
    added = await watchlist_service.add_fund(identity.user_id, payload.fund_code, payload.group_ids)
    if not added:
        raise HTTPException(status_code=404, detail="fund_not_found")
    items = await watchlist_service.list_funds(identity.user_id)
    return WatchlistResponse(items=items, total=len(items))


@router.delete("/{fund_code}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist"][0])
async def remove_from_watchlist(
    request: Request,
    fund_code: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    """把基金移出自选."""
    removed = await watchlist_service.remove_fund(identity.user_id, fund_code)
    if not removed:
        raise HTTPException(status_code=404, detail="watchlist_entry_not_found")
    return {"message": "removed"}


@router.patch("/{fund_code}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist"][0])
async def update_watchlist_entry(
    request: Request,
    fund_code: str,
    payload: WatchlistUpdateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    """更新自选基金的排序和（或）所属分组."""
    updated = await watchlist_service.update_fund(
        identity.user_id, fund_code, sort_order=payload.sort_order, group_ids=payload.group_ids
    )
    if not updated:
        raise HTTPException(status_code=404, detail="watchlist_entry_not_found")
    return {"message": "updated"}
