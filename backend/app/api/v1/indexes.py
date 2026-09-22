"""Benchmark index endpoints: selectable catalog and range history."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.fund import NavRange
from app.schemas.market import IndexCatalogResponse, IndexHistoryResponse
from app.services.market_service import market_service

router = APIRouter()


@router.get("", response_model=IndexCatalogResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def list_indexes(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> IndexCatalogResponse:
    """Benchmarks the fund-detail comparison line can be switched to."""
    items = market_service.catalog()
    return IndexCatalogResponse(items=items, total=len(items))


@router.get("/{index_code}/history", response_model=IndexHistoryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def get_index_history(
    request: Request,
    index_code: str,
    range: NavRange = Query(default="1y", description="图表区间：1m/3m/6m/1y/3y/all"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> IndexHistoryResponse:
    """Daily closes for one benchmark, served from PostgreSQL with lazy backfill."""
    history = await market_service.get_history(index_code, range)
    if history is None:
        raise HTTPException(status_code=404, detail="index_not_found")
    return history
