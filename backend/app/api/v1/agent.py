"""Agent API placeholder (MVP spec chapter 4).

Phase 1 keeps the LangGraph infrastructure (graph, checkpointer, LLM
service, tool registry, Langfuse) fully intact but exposes no real agent
capability. Future tools must reach business data only through domain
services — never direct DB access (spec 4.4).
"""

from fastapi import (
    APIRouter,
    Depends,
    Request,
)
from fastapi.responses import JSONResponse

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.schemas.base import BaseResponse

router = APIRouter()


class AgentChatRequest(BaseResponse):
    """POST /agent/chat request (reserved)."""

    message: str
    fund_code: str | None = None


@router.post("/chat")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def agent_chat(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> JSONResponse:
    """Reserved agent endpoint — returns 501 until Phase 7 (spec 4.2)."""
    logger.info(
        "agent_chat_placeholder_called",
        session_id=identity.session_id,
        user_id=identity.user_id,
    )
    return JSONResponse(
        status_code=501,
        content={
            "detail": "agent_not_implemented",
            "message": "Agent 能力将在后续阶段开放（Phase 7）",
        },
    )
