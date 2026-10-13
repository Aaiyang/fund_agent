"""持仓组合 API 端点：资产总览、持仓读写（乐观锁）与删除."""

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
from app.schemas.portfolio import (
    PortfolioSummaryResponse,
    PositionDeleteResponse,
    PositionItem,
    PositionUpsertRequest,
    PositionsResponse,
    TradeCreateRequest,
    TradePreviewResponse,
)
from app.analytics.positions import Operation
from app.analytics.allocation import allocation_scenario, portfolio_scenario_inputs
from app.schemas.research_card import AllocationChartReference, AllocationPreviewResponse
from app.repositories.fund_repository import fund_repository
from app.schemas.research import AllocationAction
from app.services.portfolio_service import (
    AccountNotFoundError,
    NavNotPublishedError,
    PositionConflictError,
    TradeInputError,
    TradeTooLargeError,
    portfolio_service,
    PortfolioService,
)

router = APIRouter()


def get_portfolio_service() -> PortfolioService:
    """当前用户账本服务依赖."""
    return portfolio_service


@router.get("/allocation-preview", response_model=AllocationPreviewResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def allocation_preview(
    request: Request,
    fund_code: str = Query(pattern=r"^\d{6}$"),
    action: AllocationAction = Query(),
    amount: float = Query(gt=0, le=1_000_000_000, allow_inf_nan=False),
    account_id: int | None = Query(default=None, ge=1),
    identity: AuthIdentity = Depends(get_current_identity),
    service: PortfolioService = Depends(get_portfolio_service),
) -> AllocationPreviewResponse:
    """只读操作情景；身份取自JWT，账户归属必须校验，不写交易."""
    if action == "compare":
        raise HTTPException(status_code=422, detail="请明确建仓、加仓、减仓或清仓")
    try:
        snapshot = await service.research_snapshot(identity.user_id, account_id)
        if await fund_repository.get_fund(fund_code) is None:
            raise HTTPException(status_code=404, detail="fund_not_found")
        data = snapshot.model_dump(mode="json")
        total, target = portfolio_scenario_inputs(data["summary"], {"positions": data["positions"]}, fund_code)
        scenario = allocation_scenario(total=total, target=target, amount=amount, action=action)
        return AllocationPreviewResponse(
            reference=AllocationChartReference(
                fund_code=fund_code, account_id=account_id, action=action, amount=amount
            ),
            captured_at=snapshot.captured_at,
            scenario=scenario,
            warnings=snapshot.warnings,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account_not_found") from exc


@router.get("/summary", response_model=PortfolioSummaryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def get_portfolio_summary(
    request: Request,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PortfolioSummaryResponse:
    """资产总览：总市值、收益、当日收益，外加按账户拆分的清单（spec 3.2）."""
    try:
        summary = await portfolio_service.get_summary(identity.user_id, account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    accounts = await portfolio_service.list_accounts(identity.user_id)
    return PortfolioSummaryResponse(summary=summary, accounts=accounts)


@router.get("/positions", response_model=PositionsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def list_positions(
    request: Request,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionsResponse:
    """列出持仓及其派生指标，可用 account_id 限定到单个账户."""
    try:
        items = await portfolio_service.list_positions(identity.user_id, account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    return PositionsResponse(items=items, total=len(items))


@router.get("/positions/{fund_code}/trades/preview", response_model=TradePreviewResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def preview_trade(
    request: Request,
    fund_code: str,
    account_id: int = Query(gt=0),
    operation: Operation = Query(description="BUY / SELL / AUTO_INVEST / CONVERT"),
    trade_date: date = Query(description="提交订单的那天"),
    after_cutoff: bool = Query(default=False, description="是否 15:00 后提交"),
    amount: float | None = Query(default=None, gt=0),
    shares: float | None = Query(default=None, gt=0),
    target_code: str | None = Query(default=None, min_length=6, max_length=6, description="转换目标基金"),
    identity: AuthIdentity = Depends(get_current_identity),
) -> TradePreviewResponse:
    """按确认日的净值给订单试算，并展示成交之后的持仓.

    相当于 ``POST /positions/{fund_code}/trades`` 的预演，但单独走一条路径，
    这样就没有字面量路径段会被 `{fund_code}` 吞掉。
    """
    try:
        return await portfolio_service.preview_trade(
            identity.user_id,
            account_id,
            fund_code,
            operation,
            trade_date,
            after_cutoff,
            amount,
            shares,
            target_code,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except NavNotPublishedError as e:
        raise HTTPException(status_code=409, detail="nav_not_published") from e
    except TradeInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/positions/{fund_code}/trades", response_model=PositionItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def record_trade(
    request: Request,
    fund_code: str,
    payload: TradeCreateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionItem:
    """记一笔买入或赎回，并用流水重新投影出该持仓."""
    try:
        return await portfolio_service.record_trade(
            identity.user_id,
            payload.account_id,
            fund_code,
            payload.operation,
            payload.trade_date,
            payload.after_cutoff,
            amount=payload.amount,
            shares=payload.shares,
            target_code=payload.target_code,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except NavNotPublishedError as e:
        logger.info("trade_nav_not_published", user_id=identity.user_id, fund_code=e.fund_code)
        raise HTTPException(status_code=409, detail="nav_not_published") from e
    except TradeInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except TradeTooLargeError as e:
        raise HTTPException(status_code=422, detail=f"shares_exceed_holding:{e.held}") from e


@router.get("/positions/{fund_code}", response_model=PositionItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def get_position(
    request: Request,
    fund_code: str,
    account_id: int | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionItem:
    """查询单个持仓；传 `account_id` 就收窄到一个账户内（spec 9.3）."""
    try:
        if account_id is not None:
            position = await portfolio_service.get_position(identity.user_id, account_id, fund_code)
        else:
            positions = await portfolio_service.list_positions(identity.user_id, None)
            position = next((item for item in positions if item.fund_code == fund_code), None)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    if position is None:
        raise HTTPException(status_code=404, detail="position_not_found")
    return position


@router.patch("/positions/{fund_code}", response_model=PositionItem)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def upsert_position(
    request: Request,
    fund_code: str,
    payload: PositionUpsertRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionItem:
    """同步持仓：按持仓页面上看到的结果重述（spec 3.7.1）.

    更新必须带 `expected_version`，版本陈旧就返回 409，这样并发的截图识别导入
    绝不可能悄悄覆盖用户的手工修改。对已有交易流水的基金，服务层会丢弃
    份额/成本/收益——这条通道只放行持有金额与首次购买日期。
    """
    try:
        return await portfolio_service.upsert_position(
            identity.user_id,
            payload.account_id,
            fund_code,
            expected_version=payload.expected_version,
            shares=payload.shares,
            market_value=payload.market_value,
            average_cost_nav=payload.average_cost_nav,
            profit_loss=payload.profit_loss,
            purchase_date=payload.purchase_date,
            reset=payload.reset,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    except PositionConflictError as e:
        logger.warning("position_version_conflict", user_id=identity.user_id, fund_code=fund_code)
        raise HTTPException(status_code=409, detail="position_version_conflict") from e


@router.delete("/positions/{fund_code}", response_model=PositionDeleteResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["portfolio"][0])
async def delete_position(
    request: Request,
    fund_code: str,
    account_id: int,
    identity: AuthIdentity = Depends(get_current_identity),
) -> PositionDeleteResponse:
    """把某只基金从账户里清掉：持仓、流水和定投计划一起删."""
    try:
        deleted = await portfolio_service.delete_position(identity.user_id, account_id, fund_code)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    if not deleted:
        raise HTTPException(status_code=404, detail="position_not_found")
    return PositionDeleteResponse(deleted=True)
