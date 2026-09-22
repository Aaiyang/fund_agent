"""Holding import API endpoints (manual + screenshot flows).

Static paths (/history) are declared before the dynamic /{import_id} route.
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
    """A missing batch is 404; a batch in the wrong state is 409.

    Reporting "not found" as 409 makes the client say "someone else updated
    this" when the real answer is that the batch does not exist for them.
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
    """The user's import batches, newest first (spec 3.6 导入记录)."""
    items = await holding_import_service.list_history(identity.user_id)
    return ImportHistoryResponse(items=items, total=len(items))


@router.post("/manual", response_model=ImportDetailResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def create_manual_import(
    request: Request,
    payload: ManualImportRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ImportDetailResponse:
    """Manual holdings entry — parsed and parked for confirmation."""
    try:
        detail = await holding_import_service.create_manual_import(
            identity.user_id,
            payload.account_id,
            payload.source_app,
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
    source_app: str | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> ScreenshotImportAccepted:
    """Upload 1..N holdings screenshots; parsing runs in the worker queue.

    Returns 202 + import_id immediately; poll GET /{import_id} for status.
    """
    try:
        record = await holding_import_service.create_screenshot_import(identity.user_id, account_id, source_app, files)
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
    """Import status + pending items with current-vs-imported diff fields."""
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
    """Correct or decide on one pending item before confirmation."""
    # Only the keys the client actually sent: passing the whole model would send
    # None for every untouched field and silently blank the user's draft values.
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
    """Apply confirmed items to official positions (the only write path)."""
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
    """Cancel a non-applied import; temp images are deleted."""
    try:
        deleted = await holding_import_service.delete_import(identity.user_id, import_id)
    except ImportStateError as e:
        raise _state_error_to_http(e) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="import_not_found")
    return {"message": "cancelled"}
