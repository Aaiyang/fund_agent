"""Chatbot API endpoints for handling chat interactions.

This module provides endpoints for chat interactions, including regular chat,
streaming chat, message history management, and chat history clearing.
"""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse

from app.api.v1.auth import get_current_session
from app.core.config import settings
from app.core.cache import cache_key, cache_service
from app.agent.graph.agent import LangGraphAgent
from app.agent.context.models import ContextInvariantError
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import llm_stream_duration_seconds
from app.models.session import Session
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Message,
    StreamResponse,
    HoldingImportDecisionResponse,
)
from app.schemas.agent_import import (
    AgentPendingAction,
    HoldingImportDecision,
    PendingActionResponse,
    HoldingImportReview,
    HoldingImportProcessing,
    HoldingImportAccountSelection,
    HoldingImportContinueRequest,
    HoldingImportAccountDecision,
)
from app.schemas.fund_selection import FundSelectionAction, FundSelectionDecision
from app.schemas.agent_resume import AgentContinueRequest
from app.schemas.human_question import HumanQuestionAction
from app.schemas.holding_import import ImportDetailResponse, ScreenshotImportAccepted
from app.services.agent_holding_import_service import (
    AgentHoldingImportService,
    agent_holding_import_service,
    get_agent_holding_import_service,
)
from app.services.holding_import_service import ImportStateError, UploadValidationError
from app.services.portfolio_service import AccountNotFoundError
from app.services.session_naming import maybe_name_session
from app.services.llm import llm_service
from app.services.llm.user_profiles import user_profile_service

router = APIRouter()
agent = LangGraphAgent()

# 上下文不变量被破坏时只回可执行文案，内部错误码留在日志里
_CONTEXT_INVARIANT_TEXT = "会话状态在本次请求中已变化，未能继续处理，请重试；如反复出现可清空该会话历史。"


@asynccontextmanager
async def _chat_execution_guard(session_id: str) -> AsyncIterator[None]:
    """普通聊天与人工恢复互斥，避免另一请求覆盖已确认任务的轮次和状态."""
    key = cache_key("agent:holding-decision", session_id)
    ttl = max(600, settings.LLM_TOTAL_TIMEOUT * 30)
    if not await cache_service.acquire_lock(key, ttl=ttl, fail_open=False):
        raise HTTPException(status_code=409, detail="agent_decision_in_progress")
    try:
        yield
    finally:
        await asyncio.shield(cache_service.release_lock(key))


async def _validate_chat_imports(session: Session, chat_request: ChatRequest) -> None:
    """拒绝跨用户/会话附件；普通聊天不能充当持仓确认指令."""
    for import_id in chat_request.holding_import_ids:
        try:
            await agent_holding_import_service.detail(session.user_id, session.id, import_id)
        except ImportStateError as exc:
            raise HTTPException(status_code=404, detail="import_not_found") from exc
    pending = await _pending_review(session)
    if pending and not (
        isinstance(pending, (HoldingImportAccountSelection, HumanQuestionAction))
        and not chat_request.holding_import_ids
    ):
        raise HTTPException(
            status_code=409,
            detail="fund_selection_pending"
            if isinstance(pending, FundSelectionAction)
            else "holding_import_review_pending",
        )
    if chat_request.holding_account_id is not None:
        try:
            await agent_holding_import_service.resolve_account(session.user_id, "", chat_request.holding_account_id)
        except AccountNotFoundError as exc:
            raise HTTPException(status_code=404, detail="account_not_found") from exc


async def _pending_review(
    session: Session, service: AgentHoldingImportService = agent_holding_import_service
) -> AgentPendingAction | None:
    """复核草稿被人工编辑后，刷新卡片内容和指纹，沿用真实中断 ID."""
    pending = await agent.get_pending_holding_review(session.id)
    if pending is None or isinstance(pending, (FundSelectionAction, HumanQuestionAction)):
        return pending
    try:
        detail = await service.detail(session.user_id, session.id, pending.import_id)
    except ImportStateError as exc:
        raise HTTPException(status_code=404, detail="import_not_found") from exc
    if isinstance(pending, HoldingImportAccountSelection):
        return pending.model_copy(update={"accounts": await service.accounts(session.user_id)})
    if not isinstance(pending, HoldingImportReview):
        return pending
    if detail.status != "REVIEW_REQUIRED":
        return pending
    fresh = await service.review(session.user_id, session.id, pending.import_id)
    return fresh.model_copy(update={"interrupt_id": pending.interrupt_id})


@router.post("/holding-imports/screenshots", response_model=ScreenshotImportAccepted, status_code=202)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def upload_holding_screenshots(
    request: Request,
    files: list[UploadFile],
    account_id: int | None = None,
    session: Session = Depends(get_current_session),
    service: AgentHoldingImportService = Depends(get_agent_holding_import_service),
) -> ScreenshotImportAccepted:
    """随问题发送的附件：先保存并绑定会话，目标可稍后补充，子图启动识别."""
    try:
        return await service.upload(session.user_id, session.id, account_id, files)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account_not_found") from exc


@router.get("/pending-action", response_model=PendingActionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def get_pending_action(
    request: Request,
    session: Session = Depends(get_current_session),
    service: AgentHoldingImportService = Depends(get_agent_holding_import_service),
) -> PendingActionResponse:
    """客户端刷新/重连时恢复待复核卡，并显示最新草稿."""
    return PendingActionResponse(
        pending_action=await _pending_review(session, service),
        continuation=await agent.get_run_continuation(session.id),
    )


@router.post("/continue", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat"][0])
async def continue_agent_run(
    request: Request,
    payload: AgentContinueRequest,
    session: Session = Depends(get_current_session),
) -> ChatResponse:
    """在人工选择后的执行错误或断线后继续原任务；会话、轮次和中断由服务端核验."""
    return await _continue_agent_run(session, payload)


async def _continue_agent_run(session: Session, payload: AgentContinueRequest) -> ChatResponse:
    """按钮和明确的自然语言继续指令共用相同锁与检查点恢复."""
    key = cache_key("agent:holding-decision", session.id)
    timeout = max(60, settings.LLM_TOTAL_TIMEOUT * 2)
    if not await cache_service.acquire_lock(key, ttl=timeout + 120, fail_open=False):
        raise HTTPException(status_code=409, detail="agent_decision_in_progress")
    try:
        profiles = await user_profile_service.execution_profiles(session.user_id)
        async with asyncio.timeout(timeout):
            with llm_service.use_profiles(profiles):
                messages = await agent.continue_run(
                    session.id,
                    payload.turn_id,
                    user_id=str(session.user_id),
                    username=session.username,
                )
        return ChatResponse(
            messages=messages,
            pending_action=await _pending_review(session),
            continuation=await agent.get_run_continuation(session.id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="agent_continuation_mismatch") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="agent_continue_timeout_check_status") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("agent_run_continue_failed", session_id=session.id, turn_id=payload.turn_id)
        raise HTTPException(status_code=503, detail="agent_continue_failed_check_status") from exc
    finally:
        await asyncio.shield(cache_service.release_lock(key))


@router.post("/fund-selection/decision", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat"][0])
async def choose_analysis_fund(
    request: Request,
    payload: FundSelectionDecision,
    session: Session = Depends(get_current_session),
) -> ChatResponse:
    """仅接受当前会话真实候选和中断 ID，选择后恢复原问题的分析."""
    key = cache_key("agent:holding-decision", session.id)
    timeout = max(60, settings.LLM_TOTAL_TIMEOUT * 2)
    if not await cache_service.acquire_lock(key, ttl=timeout + 120, fail_open=False):
        raise HTTPException(status_code=409, detail="agent_decision_in_progress")
    try:
        pending = await _pending_review(session)
        if not isinstance(pending, FundSelectionAction) or pending.interrupt_id != payload.interrupt_id:
            raise HTTPException(status_code=409, detail="fund_selection_interrupt_mismatch")
        if payload.decision == "select" and payload.fund_code not in {item.fund_code for item in pending.candidates}:
            raise HTTPException(status_code=422, detail="fund_not_in_candidates")
        profiles = await user_profile_service.execution_profiles(session.user_id)
        async with asyncio.timeout(timeout):
            with llm_service.use_profiles(profiles):
                messages = await agent.resume_holding_import(
                    session.id,
                    payload.interrupt_id,
                    payload.model_dump(),
                    user_id=str(session.user_id),
                    username=session.username,
                )
        return ChatResponse(
            messages=messages,
            pending_action=await _pending_review(session),
            continuation=await agent.get_run_continuation(session.id),
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="fund_selection_resume_timeout_check_status") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("fund_selection_resume_failed", session_id=session.id)
        raise HTTPException(status_code=503, detail="fund_selection_resume_failed_check_status") from exc
    finally:
        await asyncio.shield(cache_service.release_lock(key))


@router.get("/holding-imports/{import_id}", response_model=ImportDetailResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def get_chat_holding_import(
    request: Request,
    import_id: str,
    session: Session = Depends(get_current_session),
    service: AgentHoldingImportService = Depends(get_agent_holding_import_service),
) -> ImportDetailResponse:
    """供两个客户端轮询进度、展示完整识别结果."""
    try:
        detail = await service.detail(session.user_id, session.id, import_id)
    except ImportStateError as exc:
        raise HTTPException(status_code=404, detail="import_not_found") from exc
    return ImportDetailResponse(import_batch=detail)


@router.post("/holding-imports/{import_id}/continue", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def continue_holding_import(
    request: Request,
    import_id: str,
    payload: HoldingImportContinueRequest,
    session: Session = Depends(get_current_session),
    service: AgentHoldingImportService = Depends(get_agent_holding_import_service),
) -> ChatResponse:
    """识别任务已结束时恢复子图；不会确认或应用持仓."""
    return await _resume_import_stage(session, import_id, payload.interrupt_id, service)


@router.post("/holding-imports/{import_id}/account", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def choose_holding_import_account(
    request: Request,
    import_id: str,
    payload: HoldingImportAccountDecision,
    session: Session = Depends(get_current_session),
    service: AgentHoldingImportService = Depends(get_agent_holding_import_service),
) -> ChatResponse:
    """人工补充目标账户，只推进到复核阶段，不写正式持仓."""
    return await _resume_import_stage(session, import_id, payload.interrupt_id, service, payload.account_id)


async def _resume_import_stage(
    session: Session,
    import_id: str,
    interrupt_id: str,
    service: AgentHoldingImportService,
    account_id: int | None = None,
) -> ChatResponse:
    """选择、识别继续及最终决策共用会话锁，拒绝旧中断和跨会话恢复."""
    key = cache_key("agent:holding-decision", session.id)
    timeout = max(60, settings.LLM_TOTAL_TIMEOUT * 2)
    if not await cache_service.acquire_lock(key, ttl=timeout + 120, fail_open=False):
        raise HTTPException(status_code=409, detail="holding_import_decision_in_progress")
    try:
        pending = await _pending_review(session, service)
        if (
            pending is None
            or isinstance(pending, (FundSelectionAction, HumanQuestionAction))
            or pending.import_id != import_id
            or pending.interrupt_id != interrupt_id
        ):
            raise HTTPException(status_code=409, detail="holding_import_interrupt_mismatch")
        detail = await service.detail(session.user_id, session.id, import_id)
        if account_id is not None:
            if not isinstance(pending, HoldingImportAccountSelection):
                raise HTTPException(status_code=409, detail="holding_import_account_not_pending")
            await service.resolve_account(session.user_id, "", account_id)
            decision = {"import_id": import_id, "account_id": account_id}
        else:
            if not isinstance(pending, HoldingImportProcessing):
                raise HTTPException(status_code=409, detail="holding_import_processing_not_pending")
            if detail.status in {"UPLOADED", "PARSING"}:
                raise HTTPException(status_code=409, detail="holding_import_still_parsing")
            decision = {"import_id": import_id, "action": "continue"}
        profiles = await user_profile_service.execution_profiles(session.user_id)
        async with asyncio.timeout(timeout):
            with llm_service.use_profiles(profiles):
                messages = await agent.resume_holding_import(
                    session.id, interrupt_id, decision, user_id=str(session.user_id), username=session.username
                )
        return ChatResponse(
            messages=messages,
            pending_action=await _pending_review(session, service),
            continuation=await agent.get_run_continuation(session.id),
        )
    except ImportStateError as exc:
        raise HTTPException(status_code=404 if str(exc) == "import_not_found" else 409, detail=str(exc)) from exc
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account_not_found") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="holding_import_resume_timeout_check_status") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("holding_import_resume_failed", session_id=session.id, import_id=import_id)
        raise HTTPException(status_code=503, detail="holding_import_resume_failed_check_status") from exc
    finally:
        await asyncio.shield(cache_service.release_lock(key))


async def _chat_account_reply(session: Session, chat_request: ChatRequest) -> ChatResponse | None:
    """补充账户或明确继续原任务时恢复检查点，不把继续指令当新一轮消息."""
    if not chat_request.holding_import_ids and re.fullmatch(
        r"(?:请|帮我)?(?:继续|重试)(?:刚才|之前|原来的|原)?的?(?:分析|研究|任务|流程)?(?:一下|吧)?[。！!？?]?",
        chat_request.messages[-1].content.strip(),
    ):
        continuation = await agent.get_run_continuation(session.id)
        if continuation is not None:
            return await _continue_agent_run(session, AgentContinueRequest(turn_id=continuation.turn_id))
    pending = await _pending_review(session)
    if not isinstance(pending, HoldingImportAccountSelection):
        return None
    choice = await agent.resolve_holding_account_reply(
        pending, chat_request.messages[-1].content, str(session.user_id)
    )
    if choice is None:
        return None
    return await _resume_import_stage(
        session, pending.import_id, pending.interrupt_id, agent_holding_import_service, choice["account_id"]
    )


@router.post("/holding-imports/{import_id}/decision", response_model=HoldingImportDecisionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["holding_imports"][0])
async def decide_holding_import(
    request: Request,
    import_id: str,
    payload: HoldingImportDecision,
    session: Session = Depends(get_current_session),
    service: AgentHoldingImportService = Depends(get_agent_holding_import_service),
) -> HoldingImportDecisionResponse:
    """人工确认/取消是独立 HTTP 操作；先校验真实中断，再应用草稿并恢复 Agent."""
    timeout = max(60, settings.LLM_TOTAL_TIMEOUT * 2)
    key = cache_key("agent:holding-decision", session.id)
    if not await cache_service.acquire_lock(key, ttl=timeout + 120, fail_open=False):
        raise HTTPException(status_code=409, detail="holding_import_decision_in_progress")
    try:
        async with asyncio.timeout(timeout):
            return await _decide_holding_import(session, import_id, payload, service)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="holding_import_decision_timeout_check_status") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("holding_import_decision_failed", session_id=session.id, import_id=import_id)
        raise HTTPException(status_code=503, detail="holding_import_decision_failed_check_status") from exc
    finally:
        await asyncio.shield(cache_service.release_lock(key))


async def _decide_holding_import(
    session: Session,
    import_id: str,
    payload: HoldingImportDecision,
    service: AgentHoldingImportService,
) -> HoldingImportDecisionResponse:
    """决策和恢复串行执行；恢复失败可重试，已应用批次不会重复写入."""
    try:
        detail = await service.detail(session.user_id, session.id, import_id)
        pending = await agent.get_pending_holding_review(session.id)
        if pending is None:
            terminal = "APPLIED" if payload.decision == "confirm" else "CANCELLED"
            if detail.status == terminal:
                return HoldingImportDecisionResponse(
                    import_id=import_id,
                    status=terminal,
                    applied=detail.items_confirmed,
                    skipped=detail.items_detected - detail.items_confirmed,
                    messages=await agent.get_chat_history(session.id),
                )
            raise HTTPException(status_code=409, detail="holding_import_review_not_pending")
        if (
            isinstance(pending, (FundSelectionAction, HumanQuestionAction))
            or pending.import_id != import_id
            or pending.interrupt_id != payload.interrupt_id
        ):
            raise HTTPException(status_code=409, detail="holding_import_interrupt_mismatch")
        if payload.decision == "confirm" and not isinstance(pending, HoldingImportReview):
            raise HTTPException(status_code=409, detail="holding_import_review_not_pending")
        outcome = await service.decide(
            session.user_id,
            session.id,
            import_id,
            decision=payload.decision,
            review_digest=payload.review_digest,
        )
    except ImportStateError as exc:
        status_code = 404 if str(exc) == "import_not_found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    profiles = await user_profile_service.execution_profiles(session.user_id)
    with llm_service.use_profiles(profiles):
        messages = await agent.resume_holding_import(
            session.id,
            payload.interrupt_id,
            outcome,
            user_id=str(session.user_id),
            username=session.username,
        )
    return HoldingImportDecisionResponse(
        import_id=import_id,
        status="APPLIED" if payload.decision == "confirm" else "CANCELLED",
        applied=outcome.get("applied", 0),
        skipped=outcome.get("skipped", detail.items_detected),
        messages=messages,
        pending_action=await _pending_review(session, service),
    )


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat"][0])
async def chat(
    request: Request,
    chat_request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """Process a chat request using LangGraph.

    Args:
        request: The FastAPI request object for rate limiting.
        chat_request: The chat request containing messages.
        session: The current session from the auth token.

    Returns:
        ChatResponse: The processed chat response.

    Raises:
        HTTPException: If there's an error processing the request.
    """
    await _validate_chat_imports(session, chat_request)
    selected = await _chat_account_reply(session, chat_request)
    if selected is not None:
        return selected
    try:
        logger.info(
            "chat_request_received",
            session_id=session.id,
            message_count=len(chat_request.messages),
        )

        async with _chat_execution_guard(session.id):
            await _validate_chat_imports(session, chat_request)
            profiles = await user_profile_service.execution_profiles(session.user_id)
            messages = [Message(role="user", content=m.content) for m in chat_request.messages]
            with llm_service.use_profiles(profiles):
                if settings.SESSION_NAMING_ENABLED:
                    maybe_name_session(session.id, session.name, messages)
                result = await agent.get_response(
                    messages,
                    session.id,
                    user_id=str(session.user_id),
                    username=session.username,
                    holding_import_ids=chat_request.holding_import_ids,
                    holding_account_id=chat_request.holding_account_id,
                )
        logger.info("chat_request_processed", session_id=session.id)

        return ChatResponse(
            messages=result,
            pending_action=await _pending_review(session),
            continuation=await agent.get_run_continuation(session.id),
        )
    except HTTPException:
        raise
    except ContextInvariantError as e:
        logger.warning("chat_context_invariant_failed", session_id=session.id, code=e.code)
        raise HTTPException(status_code=409, detail=_CONTEXT_INVARIANT_TEXT) from e
    except Exception as e:
        logger.exception("chat_request_failed", session_id=session.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat_stream"][0])
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """Process a chat request using LangGraph with streaming response.

    Args:
        request: The FastAPI request object for rate limiting.
        chat_request: The chat request containing messages.
        session: The current session from the auth token.

    Returns:
        StreamingResponse: A streaming response of the chat completion.

    Raises:
        HTTPException: If there's an error processing the request.
    """
    await _validate_chat_imports(session, chat_request)
    selected = await _chat_account_reply(session, chat_request)
    try:
        logger.info(
            "stream_chat_request_received",
            session_id=session.id,
            message_count=len(chat_request.messages),
        )

        profiles = await user_profile_service.execution_profiles(session.user_id)
        messages = [Message(role="user", content=m.content) for m in chat_request.messages]

        async def event_generator():
            """Generate streaming events.

            Yields:
                str: Server-sent events in JSON format.

            Raises:
                Exception: If there's an error during streaming.
            """
            try:
                if selected is not None:
                    for message in selected.messages[-1:]:
                        if message.role == "assistant":
                            response = StreamResponse(content=message.content, done=False)
                            yield f"data: {json.dumps(response.model_dump(mode='json'))}\n\n"
                    final_response = StreamResponse(content="", done=True, pending_action=selected.pending_action)
                    yield f"data: {json.dumps(final_response.model_dump(mode='json'))}\n\n"
                    return
                async with _chat_execution_guard(session.id):
                    await _validate_chat_imports(session, chat_request)
                    with llm_service.use_profiles(profiles):
                        if settings.SESSION_NAMING_ENABLED:
                            maybe_name_session(session.id, session.name, messages)
                        with llm_stream_duration_seconds.labels(model=agent.llm_service.get_llm().get_name()).time():
                            async for chunk in agent.get_stream_response(
                                messages,
                                session.id,
                                user_id=str(session.user_id),
                                username=session.username,
                                holding_import_ids=chat_request.holding_import_ids,
                                holding_account_id=chat_request.holding_account_id,
                            ):
                                response = StreamResponse(content=chunk, done=False)
                                yield f"data: {json.dumps(response.model_dump(mode='json'))}\n\n"

                    # Send final message indicating completion
                    final_response = StreamResponse(
                        content="",
                        done=True,
                        pending_action=await _pending_review(session),
                        continuation=await agent.get_run_continuation(session.id),
                    )
                    yield f"data: {json.dumps(final_response.model_dump(mode='json'))}\n\n"

            except ContextInvariantError as e:
                logger.warning("stream_chat_context_invariant_failed", session_id=session.id, code=e.code)
                error_response = StreamResponse(content=_CONTEXT_INVARIANT_TEXT, done=True)
                yield f"data: {json.dumps(error_response.model_dump(mode='json'))}\n\n"
            except Exception as e:
                logger.exception(
                    "stream_chat_request_failed",
                    session_id=session.id,
                    error=str(e),
                )
                error_response = StreamResponse(content=str(e), done=True)
                yield f"data: {json.dumps(error_response.model_dump(mode='json'))}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.exception(
            "stream_chat_request_failed",
            session_id=session.id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def get_session_messages(
    request: Request,
    session: Session = Depends(get_current_session),
):
    """Get all messages for a session.

    Args:
        request: The FastAPI request object for rate limiting.
        session: The current session from the auth token.

    Returns:
        ChatResponse: All messages in the session.

    Raises:
        HTTPException: If there's an error retrieving the messages.
    """
    try:
        messages = await agent.get_chat_history(session.id)
        return ChatResponse(
            messages=messages,
            pending_action=await _pending_review(session),
            continuation=await agent.get_run_continuation(session.id),
        )
    except Exception as e:
        logger.exception("get_messages_failed", session_id=session.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def clear_chat_history(
    request: Request,
    session: Session = Depends(get_current_session),
):
    """Clear all messages for a session.

    Args:
        request: The FastAPI request object for rate limiting.
        session: The current session from the auth token.

    Returns:
        dict: A message indicating the chat history was cleared.
    """
    try:
        await agent.clear_chat_history(session.id)
        return {"message": "Chat history cleared successfully"}
    except Exception as e:
        logger.exception("clear_chat_history_failed", session_id=session.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
