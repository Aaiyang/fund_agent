"""业绩比较基准指数端点：可选基准目录与区间历史."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.fund import NavRange
from app.schemas.market import IndexCatalogResponse, IndexHistoryResponse, IndexQuotesResponse
from app.services.market_service import market_service

router = APIRouter()


@router.get("", response_model=IndexCatalogResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def list_indexes(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> IndexCatalogResponse:
    """基金详情页对比线可以切换到的那几只基准指数."""
    items = market_service.catalog()
    return IndexCatalogResponse(items=items, total=len(items))


@router.get("/quotes", response_model=IndexQuotesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def list_index_quotes(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> IndexQuotesResponse:
    """首页行情条用：每只基准指数的最新收盘价与当日涨跌."""
    items = await market_service.get_quotes()
    return IndexQuotesResponse(items=items, total=len(items))


@router.get("/{index_code}/history", response_model=IndexHistoryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def get_index_history(
    request: Request,
    index_code: str,
    range: NavRange = Query(default="1y", description="图表区间：1m/3m/6m/1y/3y/all"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> IndexHistoryResponse:
    """单只基准指数的日收盘价序列，从 PostgreSQL 读取并在缺数据时惰性回补."""
    history = await market_service.get_history(index_code, range)
    if history is None:
        raise HTTPException(status_code=404, detail="index_not_found")
    return history
