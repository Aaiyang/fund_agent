"""估值接口：一次请求算一批基金的盘中估值.

路由挂载在 `/valuation` 前缀下（见 `api/v1/api.py`）。
"""

from fastapi import APIRouter, Depends, Request

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.valuation import ValuationEstimateRequest, ValuationEstimatesResponse
from app.services.valuation_service import valuation_service

router = APIRouter()


@router.post("/estimates", response_model=ValuationEstimatesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["funds"][0])
async def estimate_funds(
    request: Request,
    payload: ValuationEstimateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ValuationEstimatesResponse:
    """按代码批量给出盘中估值（百分点）.

    估值是公开数据的现算，没有按用户的部分；要鉴权只是不让任何人拿这个接口免费
    驱动上游抓取。缺依据的基金在 `items` 里以 `available=False` 返回，不报错。
    """
    return await valuation_service.estimates(payload.codes)
