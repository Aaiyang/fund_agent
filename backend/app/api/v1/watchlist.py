"""Watchlist API endpoints: list/add/remove funds and group CRUD.

Route order matters: static ``/groups`` routes must be registered before the
dynamic ``/{fund_code}`` routes or "groups" would be captured as a fund code.
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
# Groups (static paths first)
# ---------------------------------------------------------------------------


@router.get("/groups", response_model=WatchlistGroupsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def list_groups(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistGroupsResponse:
    """List the user's watchlist groups."""
    items = await watchlist_service.list_groups(identity.user_id)
    return WatchlistGroupsResponse(items=items, total=len(items))


@router.post("/groups", response_model=WatchlistGroupItem, status_code=201)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def create_group(
    request: Request,
    payload: WatchlistGroupCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistGroupItem:
    """Create a custom watchlist group."""
    return await watchlist_service.create_group(identity.user_id, payload.name, payload.sort_order)


@router.patch("/groups/{group_id}", response_model=WatchlistGroupItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist_groups"][0])
async def update_group(
    request: Request,
    group_id: int,
    payload: WatchlistGroupUpdateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistGroupItem:
    """Rename, reorder, or rewrite the members of a group."""
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
    """Delete a group; member funds stay watchlisted."""
    deleted = await watchlist_service.delete_group(identity.user_id, group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="group_not_found")
    return {"message": "deleted"}


# ---------------------------------------------------------------------------
# Watchlist funds
# ---------------------------------------------------------------------------


@router.get("", response_model=WatchlistResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist"][0])
async def list_watchlist(
    request: Request,
    group_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistResponse:
    """List watchlisted funds with latest NAV and daily change."""
    items = await watchlist_service.list_funds(identity.user_id, group_id=group_id)
    return WatchlistResponse(items=items, total=len(items))


@router.post("", response_model=WatchlistResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["watchlist"][0])
async def add_to_watchlist(
    request: Request,
    payload: WatchlistAddRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> WatchlistResponse:
    """Add a fund to the watchlist (404 when the fund code is unknown)."""
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
    """Remove a fund from the watchlist."""
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
    """Update sort order and/or group memberships of a watchlisted fund."""
    updated = await watchlist_service.update_fund(
        identity.user_id, fund_code, sort_order=payload.sort_order, group_ids=payload.group_ids
    )
    if not updated:
        raise HTTPException(status_code=404, detail="watchlist_entry_not_found")
    return {"message": "updated"}
