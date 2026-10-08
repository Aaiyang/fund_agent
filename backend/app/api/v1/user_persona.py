"""已认证用户的画像管理与人工候选确认；Agent 不能调用确认接口."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.repositories.user_persona_repository import PersonaConflictError, PersonaNotFoundError
from app.schemas.user_persona import (
    PersonaClear,
    PersonaDecision,
    PersonaHistoryOut,
    PersonaOut,
    PersonaUpdate,
)
from app.services.user_persona_service import UserPersonaService, get_user_persona_service

router = APIRouter()


@contextmanager
def persona_errors() -> Iterator[None]:
    """业务冲突、缺失与数据库故障转成稳定 HTTP 状态，不暴露底层信息."""
    try:
        yield
    except PersonaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PersonaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("user_persona_database_unavailable")
        raise HTTPException(status_code=503, detail="用户画像暂不可用，请稍后重试") from exc


@router.get("", response_model=PersonaOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def get_persona(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
    service: UserPersonaService = Depends(get_user_persona_service),
) -> PersonaOut:
    """只返回当前用户的已确认画像与待复核候选."""
    with persona_errors():
        return await service.get(identity.user_id)


@router.patch("", response_model=PersonaOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def update_persona(
    request: Request,
    body: PersonaUpdate,
    identity: AuthIdentity = Depends(get_current_identity),
    service: UserPersonaService = Depends(get_user_persona_service),
) -> PersonaOut:
    """用户直接编辑，客户端不能提交其他用户 ID 或非白名单字段."""
    with persona_errors():
        return await service.update(identity.user_id, body.changes, body.expected_revision)


@router.delete("", response_model=PersonaOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def clear_persona(
    request: Request,
    body: PersonaClear,
    identity: AuthIdentity = Depends(get_current_identity),
    service: UserPersonaService = Depends(get_user_persona_service),
) -> PersonaOut:
    """清除全部画像字段、候选、证据和历史；版本继续递增."""
    with persona_errors():
        return await service.clear(identity.user_id, body.expected_revision)


@router.get("/history", response_model=list[PersonaHistoryOut])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def persona_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    identity: AuthIdentity = Depends(get_current_identity),
    service: UserPersonaService = Depends(get_user_persona_service),
) -> list[PersonaHistoryOut]:
    """读取本用户的已确认变更，最多100条."""
    with persona_errors():
        return await service.history(identity.user_id, limit)


@router.post("/proposals/{proposal_id}/decision", response_model=PersonaOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def decide_persona(
    request: Request,
    proposal_id: str,
    body: PersonaDecision,
    identity: AuthIdentity = Depends(get_current_identity),
    service: UserPersonaService = Depends(get_user_persona_service),
) -> PersonaOut:
    """人工确认或拒绝候选；过期版本409，其他用户候选404."""
    with persona_errors():
        return await service.decide(identity.user_id, proposal_id, body.decision, body.expected_revision)
