"""板块涨跌榜端点：行业/概念板块的当日快照排名."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.sector import SectorBoardKind, SectorBoardOrder, SectorBoardResponse, SectorBoardSort
from app.schemas.sector import SectorMarketRequest, SectorMarketResult, SectorScope
from app.services.sector_service import SectorService, sector_service

router = APIRouter()


def get_sector_service() -> SectorService:
    """支持端点替换数据服务进行验证."""
    return sector_service


@router.get("/market", response_model=SectorMarketResult)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def sector_market(
    request: Request,
    keyword: str = Query(min_length=1, max_length=64),
    sector_type: SectorScope = "all",
    limit: int = Query(default=3, ge=1, le=5),
    identity: AuthIdentity = Depends(get_current_identity),
    service: SectorService = Depends(get_sector_service),
) -> SectorMarketResult:
    """客户端卡片按真实BK代码取数，不接受模型行情序列."""
    result = await service.market(
        SectorMarketRequest(keyword=keyword, sector_type=sector_type, limit=limit, refresh=False)
    )
    if not result.sectors:
        raise HTTPException(status_code=503 if result.unavailable_catalogs else 404, detail="板块数据暂不可用或不存在")
    return result


@router.get("/board", response_model=SectorBoardResponse)
# 与指数行情同一档额度：为一个只读榜单去改 RATE_LIMIT_ENDPOINTS 不值得，
# 而它和指数确实是同一个使用场景（行情页同屏刷新）。
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["indexes"][0])
async def sector_board(
    request: Request,
    kind: SectorBoardKind = Query(default="industry", description="industry 行业板块、concept 概念板块"),
    order: SectorBoardOrder = Query(default="desc", description="desc 从大到小、asc 从小到大"),
    sort: SectorBoardSort = Query(default="change_pct", description="排名指标：change_pct 涨幅、amount 成交额"),
    limit: int = Query(default=10, ge=1, le=50, description="返回条数，最多 50"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> SectorBoardResponse:
    """板块榜；涨跌幅单位是百分点，取不到数时返回 503 而不是空榜."""
    result = await sector_service.board(kind, order, sort, limit)
    if not result.items:
        raise HTTPException(status_code=503, detail="板块行情暂不可用，请稍后重试")
    return result
