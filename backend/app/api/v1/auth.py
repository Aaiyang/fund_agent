"""API 的认证与鉴权端点.

本模块提供用户注册、登录、会话管理以及 token 校验相关端点。
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.agent.context import state_store
from app.agent.context.manager import context_manager
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import (
    bind_context,
    logger,
)
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import (
    CurrentUserResponse,
    SessionResponse,
    TokenResponse,
    UserCreate,
    UserProfileUpdateRequest,
    UserResponse,
)
from app.services.database import database_service
from app.utils.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_token,
)
from app.utils.sanitization import (
    sanitize_email,
    sanitize_string,
    validate_password_strength,
)

router = APIRouter()
security = HTTPBearer()
# 复用共享实例：DatabaseService.__init__ 会自建 engine，先前这里再 new 一个
# 就等于起了两套互不相干的连接池。
db_service = database_service


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """从 token 解析出当前用户.

    Args:
        credentials: 携带 JWT token 的 HTTP 鉴权凭据。

    Returns:
        User: 由 token 解析出的用户记录。

    Raises:
        HTTPException: token 无效或缺失时抛出。
    """
    try:
        # 先清洗 token
        token = sanitize_string(credentials.credentials)

        user_id = verify_token(token, expected_type="access")
        if user_id is None:
            logger.warning("invalid_token_rejected")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 确认该用户在库里存在
        user_id_int = int(user_id)
        user = await db_service.get_user(user_id_int)
        if user is None:
            logger.error("user_not_found", user_id=user_id_int)
            raise HTTPException(
                status_code=404,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 把 user_id 绑到日志上下文，本次请求后续所有日志都带上它
        bind_context(user_id=user_id_int)

        return user
    except ValueError as ve:
        logger.exception("token_validation_failed", error=str(ve))
        raise HTTPException(
            status_code=422,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Session:
    """从 token 解析出当前会话.

    Args:
        credentials: 携带 JWT token 的 HTTP 鉴权凭据。

    Returns:
        Session: 由 token 解析出的会话。

    Raises:
        HTTPException: token 无效或缺失时抛出。
    """
    try:
        # 先清洗 token
        token = sanitize_string(credentials.credentials)

        session_id = verify_token(token, expected_type="access")
        if session_id is None:
            logger.warning("invalid_session_token_rejected")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 使用前先清洗 session_id
        session_id = sanitize_string(session_id)

        # 确认该会话在库里存在
        session = await db_service.get_session(session_id)
        if session is None:
            logger.error("session_not_found", session_id=session_id)
            raise HTTPException(
                status_code=404,
                detail="Session not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 把 user_id 绑到日志上下文，本次请求后续所有日志都带上它
        bind_context(user_id=session.user_id)

        return session
    except ValueError as ve:
        logger.exception("token_validation_failed", error=str(ve))
        raise HTTPException(
            status_code=422,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )


@dataclass(frozen=True)
class AuthIdentity:
    """解析好的调用方身份：归属用户，外加所用到的聊天会话（如果有）.

    业务端点（funds、watchlist、portfolio、imports）只用到 `user_id`；
    两类 token 都接受，客户端就能直接拿登录 token 调用，不必先开一个聊天会话。
    """

    user_id: int
    session_id: str | None = None


async def get_current_identity(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthIdentity:
    """用用户 token 或聊天会话的 access token 解析出调用方身份.

    两类 token 都带 `typ: "access"`，由 subject 决定该查哪张表——用户 id 是
    纯数字，会话 id 是 UUID。

    Args:
        credentials: 携带 JWT token 的 HTTP 鉴权凭据。

    Returns:
        AuthIdentity: 该 token 所属的用户（以及会话，若适用）。

    Raises:
        HTTPException: 401 token 无效、404 subject 不存在、422 token 格式非法。
    """
    try:
        subject = verify_token(sanitize_string(credentials.credentials), expected_type="access")
        if subject is None:
            logger.warning("invalid_token_rejected")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if subject.isdigit():
            user = await db_service.get_user(int(subject))
            if user is None:
                logger.warning("user_not_found")
                raise HTTPException(
                    status_code=404,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            bind_context(user_id=user.id)
            return AuthIdentity(user_id=user.id)

        session = await db_service.get_session(subject)
        if session is None:
            logger.warning("session_not_found", session_id=subject)
            raise HTTPException(
                status_code=404,
                detail="Session not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        bind_context(user_id=session.user_id)
        return AuthIdentity(user_id=session.user_id, session_id=session.id)
    except ValueError as ve:
        logger.exception("token_validation_failed", error=str(ve))
        raise HTTPException(
            status_code=422,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/register", response_model=UserResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["register"][0])
async def register_user(request: Request, user_data: UserCreate):
    """注册新用户.

    Args:
        request: 用于限流的 FastAPI request 对象。
        user_data: 用户注册数据

    Returns:
        UserResponse: 创建出来的用户信息
    """
    try:
        # 清洗邮箱
        sanitized_email = sanitize_email(user_data.email)

        # 取出密码并校验强度
        password = user_data.password.get_secret_value()
        validate_password_strength(password)

        # 检查该用户是否已存在
        if await db_service.get_user_by_email(sanitized_email):
            raise HTTPException(status_code=400, detail="Email already registered")

        # 清洗可选的 username
        sanitized_username = sanitize_string(user_data.username) if user_data.username else None

        # 创建用户
        user = await db_service.create_user(
            email=sanitized_email,
            password=User.hash_password(password),
            username=sanitized_username,
        )

        # 签发 access token
        token = create_access_token(str(user.id))

        return UserResponse(id=user.id, email=user.email, username=user.username, token=token)
    except ValueError as ve:
        logger.exception("user_registration_validation_failed", error=str(ve))
        raise HTTPException(status_code=422, detail=str(ve))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["login"][0])
async def login(
    request: Request, email: str = Form(...), password: str = Form(...), grant_type: str = Form(default="password")
):
    """用户登录.

    Args:
        request: 用于限流的 FastAPI request 对象。
        email: 用户邮箱
        password: 用户密码
        grant_type: 必须为 "password"

    Returns:
        TokenResponse: access token 相关信息

    Raises:
        HTTPException: 凭据无效时抛出
    """
    try:
        # 清洗入参
        email = sanitize_string(email)
        grant_type = sanitize_string(grant_type)

        # 校验 grant type
        if grant_type != "password":
            raise HTTPException(
                status_code=400,
                detail="Unsupported grant type. Must be 'password'",
            )

        user = await db_service.get_user_by_email(email)
        if not user or not user.verify_password(password):
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_access_token(str(user.id))
        refresh = create_refresh_token(str(user.id))
        return TokenResponse(
            access_token=token.access_token,
            token_type="bearer",
            expires_at=token.expires_at,
            refresh_token=refresh.access_token,
        )
    except ValueError as ve:
        logger.exception("login_validation_failed", error=str(ve))
        raise HTTPException(status_code=422, detail=str(ve))


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["login"][0])
async def refresh_access_token(request: Request, refresh_token: str = Form(...)):
    """用 refresh token 换取新的 access token（spec 3.1）.

    Args:
        request: 用于限流的 FastAPI request 对象。
        refresh_token: 登录时签发出的 refresh token。

    Returns:
        TokenResponse: 新的 access token，以及轮换后的 refresh token。

    Raises:
        HTTPException: refresh token 无效或已吊销时返回 401。
    """
    try:
        payload = decode_token(sanitize_string(refresh_token), expected_type="refresh")
    except ValueError:
        payload = None
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user = await db_service.get_user(int(payload["sub"]))
    except (TypeError, ValueError):
        user = None
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 这里两边都是 naive UTC——Postgres 列存的是不带时区的 UTC 墙上时间。
    # `iat` 只精确到秒，和退出动作同一秒签发的 token 也该算已吊销，
    # 所以比较用 <=。
    revoked_at = user.refresh_revoked_at
    issued_at = payload.get("iat")
    if revoked_at is not None and isinstance(issued_at, (int, float)):
        if datetime.fromtimestamp(issued_at, UTC).replace(tzinfo=None) <= revoked_at:
            logger.warning("refresh_token_revoked", user_id=user.id)
            raise HTTPException(
                status_code=401,
                detail="Refresh token revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

    token = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    logger.info("access_token_refreshed", user_id=user.id)
    return TokenResponse(
        access_token=token.access_token,
        token_type="bearer",
        expires_at=token.expires_at,
        refresh_token=refresh.access_token,
    )


@router.post("/logout", status_code=204)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def logout(request: Request, user: User = Depends(get_current_user)) -> None:
    """吊销调用方的全部 refresh token（spec 3.1 用户退出）.

    Args:
        request: 用于限流的 FastAPI request 对象。
        user: 已鉴权的用户。

    Returns:
        None: 204 无响应体；access token 仍会有效到自己过期。
    """
    await db_service.revoke_refresh_tokens(user.id)
    logger.info("user_logged_out", user_id=user.id)


@router.get("/me", response_model=CurrentUserResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def get_current_user_info(request: Request, user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """返回已鉴权用户的信息（spec 3.1 获取当前用户信息）.

    Args:
        request: 用于限流的 FastAPI request 对象。
        user: 已鉴权的用户。

    Returns:
        CurrentUserResponse: 不含任何凭据的用户信息。
    """
    return CurrentUserResponse(id=user.id, email=user.email, username=user.username, created_at=user.created_at)


@router.patch("/me", response_model=CurrentUserResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def update_current_user_info(
    request: Request,
    payload: UserProfileUpdateRequest,
    user: User = Depends(get_current_user),
) -> CurrentUserResponse:
    """修改当前登录用户的显示名和（或）邮箱（spec 3.1）.

    Args:
        request: 用于限流的 FastAPI request 对象。
        payload: 要改的字段；没传的字段保持原值。
        user: 已鉴权的用户。

    Returns:
        CurrentUserResponse: 更新之后的用户信息。

    Raises:
        HTTPException: 新邮箱已属于别的用户时返回 400。
    """
    email = sanitize_email(payload.email) if payload.email else None
    username = sanitize_string(payload.username) if payload.username is not None else None

    if email and email != user.email:
        if await db_service.get_user_by_email(email):
            raise HTTPException(status_code=400, detail="Email already registered")

    updated = await db_service.update_user(user.id, email=email, username=username)
    if updated is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return CurrentUserResponse(
        id=updated.id, email=updated.email, username=updated.username, created_at=updated.created_at
    )


@router.post("/session", response_model=SessionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def create_session(request: Request, user: User = Depends(get_current_user)):
    """为已鉴权用户新建一个聊天会话.

    Args:
        request: 用于限流的 FastAPI request 对象。
        user: 已鉴权的用户

    Returns:
        SessionResponse: 会话 ID、名称与 access token
    """
    try:
        # 生成唯一的 session_id
        session_id = str(uuid.uuid4())

        # 在库里创建会话，同时把 username 抄一份进去，供 LLM 做个性化
        session = await db_service.create_session(session_id, user.id, username=user.username)

        # 为该会话签发 access token
        token = create_access_token(session_id)

        logger.info(
            "session_created",
            session_id=session_id,
            user_id=user.id,
            name=session.name,
            expires_at=token.expires_at.isoformat(),
        )

        return SessionResponse(session_id=session_id, name=session.name, token=token)
    except ValueError as ve:
        logger.exception("session_creation_validation_failed", error=str(ve), user_id=user.id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.patch("/session/{session_id}/name", response_model=SessionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def update_session_name(
    request: Request,
    session_id: str,
    name: str = Form(...),
    current_session: Session = Depends(get_current_session),
):
    """修改会话名称.

    Args:
        request: 用于限流的 FastAPI request 对象。
        session_id: 要更新的会话 ID
        name: 会话的新名称
        current_session: 鉴权得到的当前会话

    Returns:
        SessionResponse: 更新后的会话信息
    """
    try:
        # 清洗入参
        sanitized_session_id = sanitize_string(session_id)
        sanitized_name = sanitize_string(name)
        sanitized_current_session = sanitize_string(current_session.id)

        # 校验路径上的 session_id 就是当前鉴权出来的那个会话
        if sanitized_session_id != sanitized_current_session:
            raise HTTPException(status_code=403, detail="Cannot modify other sessions")

        # 更新会话名称
        session = await db_service.update_session_name(sanitized_session_id, sanitized_name)

        # 重新签发一个 token（并非必需，只是保持返回结构一致）
        token = create_access_token(sanitized_session_id)

        return SessionResponse(session_id=sanitized_session_id, name=session.name, token=token)
    except ValueError as ve:
        logger.exception("session_update_validation_failed", error=str(ve), session_id=session_id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.delete("/session/{session_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def delete_session(request: Request, session_id: str, current_session: Session = Depends(get_current_session)):
    """删除当前登录用户名下的一个会话.

    Args:
        request: 用于限流的 FastAPI request 对象。
        session_id: 要删除的会话 ID
        current_session: 鉴权得到的当前会话

    Returns:
        None
    """
    try:
        # 清洗入参
        sanitized_session_id = sanitize_string(session_id)
        sanitized_current_session = sanitize_string(current_session.id)

        # 校验路径上的 session_id 就是当前鉴权出来的那个会话
        if sanitized_session_id != sanitized_current_session:
            raise HTTPException(status_code=403, detail="Cannot delete other sessions")

        # 删除会话
        await db_service.delete_session(sanitized_session_id)

        # 摘要状态随会话行一起消失；再把 LangGraph checkpoint 一并清掉
        # （best-effort：清理失败不回滚删除，只记日志）
        checkpoints_removed = await state_store.delete_thread_checkpoints(sanitized_session_id)
        context_manager.forget_thread(sanitized_session_id)

        logger.info(
            "session_deleted",
            session_id=session_id,
            user_id=current_session.user_id,
            checkpoints_removed=checkpoints_removed,
        )
    except ValueError as ve:
        logger.exception("session_deletion_validation_failed", error=str(ve), session_id=session_id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.get("/sessions", response_model=List[SessionResponse])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def get_user_sessions(request: Request, user: User = Depends(get_current_user)):
    """取出已鉴权用户的全部会话 ID.

    Args:
        request: 用于限流的 FastAPI request 对象。
        user: 已鉴权的用户

    Returns:
        List[SessionResponse]: 会话 ID 列表
    """
    try:
        sessions = await db_service.get_user_sessions(user.id)
        return [
            SessionResponse(
                session_id=sanitize_string(session.id),
                name=sanitize_string(session.name),
                token=create_access_token(session.id),
            )
            for session in sessions
        ]
    except ValueError as ve:
        logger.exception("get_sessions_validation_failed", user_id=user.id, error=str(ve))
        raise HTTPException(status_code=422, detail=str(ve))
