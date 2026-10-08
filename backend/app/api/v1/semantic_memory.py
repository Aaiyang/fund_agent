"""当前用户的记忆查看、直接纠错、删除、开关和失败任务恢复."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.repositories.semantic_memory_repository import MemoryConflictError, MemoryNotFoundError
from app.schemas.semantic_memory import (
    MemoryClear,
    MemoryDelete,
    MemoryEdit,
    MemoryItemOut,
    MemoryJobOut,
    MemorySettingsOut,
    MemorySettingsUpdate,
)
from app.services.memory import MemoryService, get_memory_service

router = APIRouter()


@contextmanager
def memory_errors() -> Iterator[None]:
    """稳定业务状态码，不把数据库或供应商详情传给客户端."""
    try:
        yield
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("memory_management_database_unavailable")
        raise HTTPException(status_code=503, detail="记忆管理暂不可用，请稍后重试") from exc


@router.get("", response_model=list[MemoryItemOut])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def list_memories(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> list[MemoryItemOut]:
    """只列出当前用户未删除、未过期的事实及来源."""
    with memory_errors():
        return await service.list_memories(identity.user_id, limit)


@router.get("/settings", response_model=MemorySettingsOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def get_memory_settings(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> MemorySettingsOut:
    """读取用户开关与并发控制版本."""
    with memory_errors():
        return await service.get_settings(identity.user_id)


@router.patch("/settings", response_model=MemorySettingsOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def update_memory_settings(
    request: Request,
    body: MemorySettingsUpdate,
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> MemorySettingsOut:
    """关闭停止召回与新写入；已有事实仍可通过管理接口查看/删除."""
    with memory_errors():
        return await service.control(identity.user_id, body.expected_revision, body.enabled)


@router.delete("", response_model=MemorySettingsOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def clear_memories(
    request: Request,
    body: MemoryClear,
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> MemorySettingsOut:
    """立即抹除应用记忆正文，取消旧写入，向量删除交由可恢复任务完成."""
    with memory_errors():
        return await service.control(identity.user_id, body.expected_revision)


@router.get("/jobs", response_model=list[MemoryJobOut])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def memory_jobs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> list[MemoryJobOut]:
    """任务账本不暴露聊天原文或底层错误文本."""
    with memory_errors():
        return await service.list_jobs(identity.user_id, limit)


@router.post("/jobs/{job_id}/retry", response_model=MemoryJobOut)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def retry_memory_job(
    request: Request,
    job_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryJobOut:
    """仅当前用户可重新排队当前代际失败任务."""
    with memory_errors():
        return await service.retry_job(identity.user_id, job_id)


@router.patch("/{memory_id}", status_code=204)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def edit_memory(
    request: Request,
    memory_id: str,
    body: MemoryEdit,
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> Response:
    """直接按用户提交内容纠错，不让模型再次解释或猜测."""
    with memory_errors():
        await service.edit(identity.user_id, memory_id, body.expected_version, body.content)
    return Response(status_code=204)


@router.delete("/{memory_id}", status_code=204)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def delete_memory(
    request: Request,
    memory_id: str,
    body: MemoryDelete,
    identity: AuthIdentity = Depends(get_current_identity),
    service: MemoryService = Depends(get_memory_service),
) -> Response:
    """带版本保护地忘记一条记忆，立即阻止旧向量召回."""
    with memory_errors():
        await service.edit(identity.user_id, memory_id, body.expected_version, None)
    return Response(status_code=204)
