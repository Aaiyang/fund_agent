"""Base response schemas shared across all endpoints."""

from uuid import UUID, uuid4

from asgi_correlation_id import correlation_id
from pydantic import BaseModel, Field


def _get_request_id() -> UUID:
    """Return the current request's correlation ID, or a fresh UUID as fallback."""
    value = correlation_id.get()
    return UUID(value) if value else uuid4()


class BaseResponse(BaseModel):
    """Base response model that all endpoint responses inherit from.

    request_id is auto-populated from the CorrelationIdMiddleware ContextVar —
    no endpoint needs to pass it explicitly.
    """

    request_id: UUID = Field(default_factory=_get_request_id, description="Unique identifier for this request")


def clean_required_text(value: str | None) -> str | None:
    """Trim user text and reject anything blank once trimmed.

    `min_length=1` happily accepts "   ", which then renders as an unnamed row.
    None stays None so PATCH bodies can keep meaning "leave this alone".
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise ValueError("value must not be blank")
    return text
