"""长期记忆任务仅携带用户 ID，原文与重试状态保存在数据库账本."""

from app.core.task_queue import broker
from app.services.memory import memory_service
from app.workers import MEMORY_WRITE_TASK


@broker.task(task_name=MEMORY_WRITE_TASK)
async def process_memory_user_task(user_id: int) -> None:
    """咨询锁保护同用户任务串行执行，重复投递安全返回."""
    await memory_service.process_user(user_id)
