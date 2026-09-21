"""This file contains the authentication utilities for the application."""

import re
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Optional

from jose import (
    JWTError,
    jwt,
)

from app.core.config import settings
from app.core.logging import logger
from app.schemas.auth import Token
from app.utils.sanitization import sanitize_string


def create_access_token(thread_id: str, expires_delta: Optional[timedelta] = None) -> Token:
    """Create a new access token for a thread.

    Args:
        thread_id: The unique thread ID for the conversation.
        expires_delta: Optional expiration time delta.

    Returns:
        Token: The generated access token.
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "sub": thread_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "typ": "access",
        "jti": sanitize_string(f"{thread_id}-{datetime.now(UTC).timestamp()}"),  # Add unique token identifier
    }

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    logger.info("token_created", thread_id=thread_id, expires_at=expire.isoformat())

    return Token(access_token=encoded_jwt, expires_at=expire)


def create_refresh_token(subject_id: str) -> Token:
    """Create a long-lived refresh token (separate `typ` claim).

    Args:
        subject_id: The user id the refresh token is bound to.

    Returns:
        Token: The generated refresh token.
    """
    expire = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": subject_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "typ": "refresh",
        "jti": sanitize_string(f"refresh-{subject_id}-{datetime.now(UTC).timestamp()}"),
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    logger.info("refresh_token_created", subject_id=subject_id, expires_at=expire.isoformat())
    return Token(access_token=encoded_jwt, expires_at=expire)


def decode_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
    """Decode a JWT and return its claims, rejecting mismatched token types.

    Args:
        token: The JWT token to verify.
        expected_type: When set, reject tokens whose `typ` claim differs
            (e.g. "refresh" tokens must never be accepted as access tokens).
            Tokens minted before `typ` existed default to "access".

    Returns:
        Optional[dict]: The claims when valid, None otherwise.

    Raises:
        ValueError: If the token is not a well-formed JWT string.
    """
    if not token or not isinstance(token, str):
        logger.warning("token_invalid_format")
        raise ValueError("Token must be a non-empty string")

    # Basic format validation before attempting decode
    # JWT tokens consist of 3 base64url-encoded segments separated by dots
    if not re.match(r"^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$", token):
        logger.warning("token_suspicious_format")
        raise ValueError("Token format is invalid - expected JWT format")

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        logger.error("token_verification_failed", error=str(e))
        return None

    if expected_type is not None and payload.get("typ", "access") != expected_type:
        logger.warning("token_type_mismatch", expected=expected_type, got=payload.get("typ"))
        return None
    if payload.get("sub") is None:
        logger.warning("token_missing_subject")
        return None
    return payload


def verify_token(token: str, expected_type: Optional[str] = None) -> Optional[str]:
    """Verify a JWT token and return the thread ID or user id in `sub`.

    Args:
        token: The JWT token to verify.
        expected_type: When set, reject tokens whose `typ` claim differs.

    Returns:
        Optional[str]: The subject if token is valid, None otherwise.

    Raises:
        ValueError: If the token format is invalid
    """
    payload = decode_token(token, expected_type)
    if payload is None:
        return None

    subject: str = payload["sub"]
    logger.info("token_verified", thread_id=subject)
    return subject
