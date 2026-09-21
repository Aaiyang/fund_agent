"""Screenshot import worker task (Taskiq)."""

from app.core.logging import logger
from app.core.task_queue import broker
from app.services.holding_import_service import holding_import_service


@broker.task
async def process_screenshot_import_task(import_id: str, user_id: int) -> str:
    """Parse uploaded screenshots into a review-ready draft.

    Runs in the Taskiq worker (Redis broker) or, in the degraded no-Redis
    fallback, in-process in the background. Status transitions are tracked
    in PostgreSQL either way.
    """
    try:
        await holding_import_service.process_screenshot_import(import_id, user_id)
        return "ok"
    except Exception as e:
        logger.exception("screenshot_import_task_failed", import_id=import_id, error=str(e))
        await holding_import_service.mark_failed(import_id, str(e))
        return "failed"
