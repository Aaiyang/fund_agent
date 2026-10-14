"""Resolve a report reference from the authenticated session's checkpoint, never client prose."""

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.types import StateSnapshot

from app.schemas.research import ResearchTask


class ResearchFollowupError(ValueError):
    """A missing source or unfinished run requires a client-visible guard response."""

    def __init__(self, code: str, status_code: int = 404) -> None:
        """Carry a safe HTTP error code without including checkpoint contents."""
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def research_source(message: BaseMessage) -> ResearchTask | None:
    """Read only server-generated, eligible source-report metadata."""
    if not isinstance(message, AIMessage):
        return None
    raw = message.additional_kwargs.get("research_source")
    if raw is None:
        return None
    try:
        task = ResearchTask.model_validate(raw)
    except ValueError:
        return None
    if task.request.strategy != "single" or task.request.intent in {"sector_research", "stock_research"}:
        return None
    return task


def validate_research_followup(state: StateSnapshot, reference: str) -> ResearchTask:
    """Source lookup is scoped to this session; unresolved interrupts cannot be bypassed."""
    if state.next:
        raise ResearchFollowupError("agent_run_pending", 409)
    for message in reversed(state.values.get("messages", [])):
        source = research_source(message)
        if source is not None and source.turn_id == reference:
            request = source.request.model_copy(update={"strategy": "multi_role", "mode": "deep"})
            return source.model_copy(
                update={"request": request, "source_research_id": reference, "requested_by": "followup"}
            )
    raise ResearchFollowupError("research_source_not_found")


def completed_followup(state: StateSnapshot, reference: str) -> AIMessage | None:
    """A repeated button request returns the already saved report without another run."""
    return next(
        (
            message
            for message in reversed(state.values.get("messages", []))
            if isinstance(message, AIMessage)
            and message.additional_kwargs.get("research_followup_source") == reference
        ),
        None,
    )
