"""定投计划端点：列表（读取时先结算）、新增、修改、删除."""

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
from app.schemas.auto_invest import (
    AutoInvestPlanCreateRequest,
    AutoInvestPlanItem,
    AutoInvestPlansResponse,
    AutoInvestPlanUpdateRequest,
)
from app.services.auto_invest_service import (
    PlanInputError,
    PlanNotFoundError,
    auto_invest_service,
)
from app.services.portfolio_service import AccountNotFoundError

router = APIRouter()


@router.get("/plans", response_model=AutoInvestPlansResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auto_invest"][0])
async def list_plans(
    request: Request,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AutoInvestPlansResponse:
    """列出定投计划，返回前先把所有已到期的期数结算掉."""
    items, settled = await auto_invest_service.list_plans(identity.user_id, account_id)
    return AutoInvestPlansResponse(items=items, total=len(items), settled=settled)


@router.post("/plans", response_model=AutoInvestPlanItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auto_invest"][0])
async def create_plan(
    request: Request,
    payload: AutoInvestPlanCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AutoInvestPlanItem:
    """新增一份定投计划，即按周期定期买入的安排."""
    try:
        return await auto_invest_service.create_plan(
            identity.user_id,
            payload.account_id,
            payload.fund_code,
            payload.amount,
            payload.frequency,
            payload.run_day,
            payload.start_date,
            payload.end_date,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except PlanInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.patch("/plans/{plan_id}", response_model=AutoInvestPlanItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auto_invest"][0])
async def update_plan(
    request: Request,
    plan_id: int,
    payload: AutoInvestPlanUpdateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> AutoInvestPlanItem:
    """修改定投安排；已经写入的期数不做回溯重算."""
    try:
        return await auto_invest_service.update_plan(
            identity.user_id,
            plan_id,
            amount=payload.amount,
            frequency=payload.frequency,
            run_day=payload.run_day,
            start_date=payload.start_date,
            end_date=payload.end_date,
            active=payload.active,
        )
    except PlanNotFoundError as e:
        raise HTTPException(status_code=404, detail="plan_not_found") from e
    except PlanInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/plans/{plan_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auto_invest"][0])
async def delete_plan(
    request: Request,
    plan_id: int,
    with_orders: bool = Query(default=False, description="同时删掉这个计划生成的定投流水"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, bool]:
    """删除计划；`with_orders` 为真时把它已生成的定投流水一并删掉."""
    deleted = await auto_invest_service.delete_plan(identity.user_id, plan_id, with_orders)
    if not deleted:
        raise HTTPException(status_code=404, detail="plan_not_found")
    return {"deleted": True}
