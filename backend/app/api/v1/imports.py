"""持仓导入 API 端点（手动录入 + 截图识别导入两条流程）.

静态路径（/history）必须声明在动态路由 /{import_id} 之前。
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.schemas.holding_import import (
    ImportConfirmResponse,
    ImportDetailResponse,
    ImportHistoryResponse,
    ImportItemOut,
    ImportItemUpdateRequest,
    ManualImportRequest,
    ScreenshotImportAccepted,
)
from app.services.holding_import_service import (
    ImportStateError,
    UploadValidationError,
    holding_import_service,
)
from app.services.portfolio_service import AccountNotFoundError

router = APIRouter()


def _state_error_to_http(exc: ImportStateError) -> HTTPException:
    """批次不存在给 404，批次状态不允许该操作给 409.

    把“查无此批次”也报成 409，客户端会提示“这里被别人改过了”，而真实情况
    是这个批次对该用户根本不存在。
    """
    detail = str(exc)
    status = 404 if detail.endswith("_not_found") else 409
    return HTTPException(status_code=status, detail=detail)


@router.get("/history", response_model=ImportHistoryResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def list_import_history(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ImportHistoryResponse:
    """按时间倒序列出该用户的导入批次（spec 3.6 导入记录）."""
    items = await holding_import_service.list_history(identity.user_id)
    return ImportHistoryResponse(items=items, total=len(items))


@router.post("/manual", response_model=ImportDetailResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def create_manual_import(
    request: Request,
    payload: ManualImportRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ImportDetailResponse:
    """手动录入持仓：解析入库后挂起，等用户确认."""
    try:
        detail = await holding_import_service.create_manual_import(
            identity.user_id,
            payload.account_id,
            payload.positions,
        )
    except UploadValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    return ImportDetailResponse(import_batch=detail)


@router.post("/screenshots", response_model=ScreenshotImportAccepted, status_code=202)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def create_screenshot_import(
    request: Request,
    account_id: int,
    files: list[UploadFile],
    identity: AuthIdentity = Depends(get_current_identity),
) -> ScreenshotImportAccepted:
    """上传 1..N 张持仓截图，解析工作交给后台 worker 队列.

    立即返回 202 与 import_id，之后轮询 GET /{import_id} 取进度。
    """
    try:
        record = await holding_import_service.create_screenshot_import(identity.user_id, account_id, files)
    except UploadValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail="account_not_found") from e
    logger.info("screenshot_import_accepted", import_id=record.id, user_id=identity.user_id)
    return ScreenshotImportAccepted(import_id=record.id, status=record.status, image_count=record.image_count)


@router.get("/{import_id}", response_model=ImportDetailResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def get_import_detail(
    request: Request,
    import_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ImportDetailResponse:
    """导入进度 + 待确认条目，条目带上“当前持仓/导入结果”的差异字段."""
    detail = await holding_import_service.get_import_detail(identity.user_id, import_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="import_not_found")
    return ImportDetailResponse(import_batch=detail)


@router.patch("/{import_id}/items/{item_id}", response_model=ImportItemOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def update_import_item(
    request: Request,
    import_id: str,
    item_id: int,
    payload: ImportItemUpdateRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ImportItemOut:
    """在确认之前修正某条待确认条目，或对它做出裁决."""
    # 只取客户端真正提交过的键：整个模型都传下去会把没改过的字段全带上 None，
    # 悄悄把用户填好的草稿值清掉。
    fields = payload.model_dump(exclude_unset=True)
    user_action = fields.pop("user_action", None)
    try:
        return await holding_import_service.update_item(
            identity.user_id,
            import_id,
            item_id,
            user_action=user_action,
            **fields,
        )
    except ImportStateError as e:
        raise _state_error_to_http(e) from e


@router.post("/{import_id}/confirm", response_model=ImportConfirmResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def confirm_import(
    request: Request,
    import_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ImportConfirmResponse:
    """把已确认的条目写进正式持仓（唯一的写入路径）."""
    try:
        result = await holding_import_service.confirm_import(identity.user_id, import_id)
    except ImportStateError as e:
        raise _state_error_to_http(e) from e
    return ImportConfirmResponse(import_id=import_id, applied=result["applied"], skipped=result["skipped"])


@router.delete("/{import_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def delete_import(
    request: Request,
    import_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    """取消尚未应用的导入批次，同时删掉临时图片."""
    try:
        deleted = await holding_import_service.delete_import(identity.user_id, import_id)
    except ImportStateError as e:
        raise _state_error_to_http(e) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="import_not_found")
    return {"message": "cancelled"}
