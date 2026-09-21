"""Fund API endpoints: search, detail, NAV history, performance, refresh."""

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
from app.core.task_queue import broker
from app.schemas.fund import (
    FundDetailResponse,
    FundNavHistoryResponse,
    FundPerformanceResponse,
    FundSearchResponse,
    FundSyncStatusResponse,
    RelatedSectorsResponse,
)
from app.services.fund_service import fund_service

router = APIRouter()


@router.get("/search", response_model=FundSearchResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds_search"][0])
async def search_funds(
    request: Request,
    q: str = Query(min_length=1, max_length=50, description="基金代码 / 名称 / 模糊关键词"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> FundSearchResponse:
    """Search funds by code, full name, abbreviation or fuzzy name."""
    logger.info("fund_search_requested", session_id=identity.session_id, user_id=identity.user_id)
    items = await fund_service.search(q, user_id=identity.user_id)
    return FundSearchResponse(items=items, total=len(items))


@router.get("/{fund_code}", response_model=FundDetailResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds"][0])
async def get_fund_detail(
    request: Request,
    fund_code: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> FundDetailResponse:
    """Fund overview: identity, latest NAV, computed performance (spec 3.5.1)."""
    detail = await fund_service.get_detail(fund_code, user_id=identity.user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="fund_not_found")
    return detail


@router.get("/{fund_code}/nav", response_model=FundNavHistoryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds"][0])
async def get_fund_nav_history(
    request: Request,
    fund_code: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    identity: AuthIdentity = Depends(get_current_identity),
) -> FundNavHistoryResponse:
    """Historical NAV series served from PostgreSQL (never live pass-through)."""
    return await fund_service.get_nav_history(fund_code, start_date, end_date)


@router.get("/{fund_code}/performance", response_model=FundPerformanceResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds"][0])
async def get_fund_performance(
    request: Request,
    fund_code: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> FundPerformanceResponse:
    """Deterministic period analytics computed by backend Python (spec 5.2)."""
    detail = await fund_service.get_detail(fund_code, user_id=identity.user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="fund_not_found")
    return FundPerformanceResponse(fund_code=fund_code, performance=detail.performance)


@router.get("/{fund_code}/related-sectors", response_model=RelatedSectorsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds"][0])
async def get_related_sectors(
    request: Request,
    fund_code: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> RelatedSectorsResponse:
    """Related sectors placeholder — not a hard MVP data dependency (spec 5.7)."""
    return RelatedSectorsResponse(fund_code=fund_code)


@router.post("/{fund_code}/refresh", response_model=FundSyncStatusResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds"][0])
async def refresh_fund_data(
    request: Request,
    fund_code: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> FundSyncStatusResponse:
    """Enqueue a background sync for one fund (returns immediately)."""
    from app.workers.fund_sync import sync_fund_task

    await sync_fund_task.kiq(fund_code)
    logger.info("fund_refresh_requested", fund_code=fund_code, session_id=identity.session_id)
    return FundSyncStatusResponse(fund_code=fund_code, queued=bool(broker))
