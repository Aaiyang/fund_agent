"""Authentication and authorization endpoints for the API.

This module provides endpoints for user registration, login, session management,
and token verification.
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
# Reuse the shared instance: DatabaseService.__init__ builds its own engine, so a
# second instance here meant two independent connection pools.
db_service = database_service


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """Get the current user ID from the token.

    Args:
        credentials: The HTTP authorization credentials containing the JWT token.

    Returns:
        User: The user extracted from the token.

    Raises:
        HTTPException: If the token is invalid or missing.
    """
    try:
        # Sanitize token
        token = sanitize_string(credentials.credentials)

        user_id = verify_token(token, expected_type="access")
        if user_id is None:
            logger.warning("invalid_token_rejected")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Verify user exists in database
        user_id_int = int(user_id)
        user = await db_service.get_user(user_id_int)
        if user is None:
            logger.error("user_not_found", user_id=user_id_int)
            raise HTTPException(
                status_code=404,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Bind user_id to logging context for all subsequent logs in this request
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
    """Get the current session ID from the token.

    Args:
        credentials: The HTTP authorization credentials containing the JWT token.

    Returns:
        Session: The session extracted from the token.

    Raises:
        HTTPException: If the token is invalid or missing.
    """
    try:
        # Sanitize token
        token = sanitize_string(credentials.credentials)

        session_id = verify_token(token, expected_type="access")
        if session_id is None:
            logger.warning("invalid_session_token_rejected")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Sanitize session_id before using it
        session_id = sanitize_string(session_id)

        # Verify session exists in database
        session = await db_service.get_session(session_id)
        if session is None:
            logger.error("session_not_found", session_id=session_id)
            raise HTTPException(
                status_code=404,
                detail="Session not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Bind user_id to logging context for all subsequent logs in this request
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
    """Resolved caller: the owning user, plus the chat session when one was used.

    Business endpoints (funds, watchlist, portfolio, imports) only need
    `user_id`; accepting both token flavors means a client can use its login
    token without first opening a chat session.
    """

    user_id: int
    session_id: str | None = None


async def get_current_identity(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthIdentity:
    """Resolve the caller from a user token or a chat-session access token.

    Both carry `typ: "access"`; the subject decides which table to check —
    user ids are numeric, session ids are UUIDs.

    Args:
        credentials: The HTTP authorization credentials containing the JWT token.

    Returns:
        AuthIdentity: The user (and session, when applicable) the token belongs to.

    Raises:
        HTTPException: 401 invalid token, 404 unknown subject, 422 malformed token.
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
    """Register a new user.

    Args:
        request: The FastAPI request object for rate limiting.
        user_data: User registration data

    Returns:
        UserResponse: The created user info
    """
    try:
        # Sanitize email
        sanitized_email = sanitize_email(user_data.email)

        # Extract and validate password
        password = user_data.password.get_secret_value()
        validate_password_strength(password)

        # Check if user exists
        if await db_service.get_user_by_email(sanitized_email):
            raise HTTPException(status_code=400, detail="Email already registered")

        # Sanitize optional username
        sanitized_username = sanitize_string(user_data.username) if user_data.username else None

        # Create user
        user = await db_service.create_user(
            email=sanitized_email,
            password=User.hash_password(password),
            username=sanitized_username,
        )

        # Create access token
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
    """Login a user.

    Args:
        request: The FastAPI request object for rate limiting.
        email: User's email
        password: User's password
        grant_type: Must be "password"

    Returns:
        TokenResponse: Access token information

    Raises:
        HTTPException: If credentials are invalid
    """
    try:
        # Sanitize inputs
        email = sanitize_string(email)
        grant_type = sanitize_string(grant_type)

        # Verify grant type
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
    """Exchange a refresh token for a new access token (spec 3.1).

    Args:
        request: The FastAPI request object for rate limiting.
        refresh_token: The refresh token issued at login.

    Returns:
        TokenResponse: A fresh access token and a rotated refresh token.

    Raises:
        HTTPException: 401 when the refresh token is invalid or revoked.
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

    # Logout revokes by stamping the user: anything minted before the stamp is dead.
    # Both sides are naive UTC here — Postgres columns store UTC wall time without tz.
    revoked_at = user.refresh_revoked_at
    issued_at = payload.get("iat")
    if revoked_at is not None and isinstance(issued_at, (int, float)):
        if datetime.fromtimestamp(issued_at, UTC).replace(tzinfo=None) < revoked_at:
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
    """Revoke the caller's refresh tokens (spec 3.1 用户退出).

    Args:
        request: The FastAPI request object for rate limiting.
        user: The authenticated user.

    Returns:
        None: 204 with no body. Access tokens stay valid until they expire.
    """
    await db_service.revoke_refresh_tokens(user.id)
    logger.info("user_logged_out", user_id=user.id)


@router.get("/me", response_model=CurrentUserResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["auth"][0])
async def get_current_user_info(request: Request, user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """Return the authenticated user's profile (spec 3.1 获取当前用户信息).

    Args:
        request: The FastAPI request object for rate limiting.
        user: The authenticated user.

    Returns:
        CurrentUserResponse: Profile without credentials.
    """
    return CurrentUserResponse(id=user.id, email=user.email, username=user.username, created_at=user.created_at)


@router.post("/session", response_model=SessionResponse)
async def create_session(user: User = Depends(get_current_user)):
    """Create a new chat session for the authenticated user.

    Args:
        user: The authenticated user

    Returns:
        SessionResponse: The session ID, name, and access token
    """
    try:
        # Generate a unique session ID
        session_id = str(uuid.uuid4())

        # Create session in database, copying username for LLM personalization
        session = await db_service.create_session(session_id, user.id, username=user.username)

        # Create access token for the session
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
async def update_session_name(
    session_id: str, name: str = Form(...), current_session: Session = Depends(get_current_session)
):
    """Update a session's name.

    Args:
        session_id: The ID of the session to update
        name: The new name for the session
        current_session: The current session from auth

    Returns:
        SessionResponse: The updated session information
    """
    try:
        # Sanitize inputs
        sanitized_session_id = sanitize_string(session_id)
        sanitized_name = sanitize_string(name)
        sanitized_current_session = sanitize_string(current_session.id)

        # Verify the session ID matches the authenticated session
        if sanitized_session_id != sanitized_current_session:
            raise HTTPException(status_code=403, detail="Cannot modify other sessions")

        # Update the session name
        session = await db_service.update_session_name(sanitized_session_id, sanitized_name)

        # Create a new token (not strictly necessary but maintains consistency)
        token = create_access_token(sanitized_session_id)

        return SessionResponse(session_id=sanitized_session_id, name=session.name, token=token)
    except ValueError as ve:
        logger.exception("session_update_validation_failed", error=str(ve), session_id=session_id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, current_session: Session = Depends(get_current_session)):
    """Delete a session for the authenticated user.

    Args:
        session_id: The ID of the session to delete
        current_session: The current session from auth

    Returns:
        None
    """
    try:
        # Sanitize inputs
        sanitized_session_id = sanitize_string(session_id)
        sanitized_current_session = sanitize_string(current_session.id)

        # Verify the session ID matches the authenticated session
        if sanitized_session_id != sanitized_current_session:
            raise HTTPException(status_code=403, detail="Cannot delete other sessions")

        # Delete the session
        await db_service.delete_session(sanitized_session_id)

        logger.info("session_deleted", session_id=session_id, user_id=current_session.user_id)
    except ValueError as ve:
        logger.exception("session_deletion_validation_failed", error=str(ve), session_id=session_id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.get("/sessions", response_model=List[SessionResponse])
async def get_user_sessions(user: User = Depends(get_current_user)):
    """Get all session IDs for the authenticated user.

    Args:
        user: The authenticated user

    Returns:
        List[SessionResponse]: List of session IDs
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
