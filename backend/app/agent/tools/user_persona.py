"""用户画像工具只提出候选，不能直接确认、清除或改变权限."""

from langchain_core.tools import tool

from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import get_tool_runtime
from app.repositories.user_persona_repository import PersonaLimitError
from app.schemas.user_persona import PersonaPatch
from app.services.user_persona_service import user_persona_service


@tool
@tool_result
async def propose_user_profile_update(changes: PersonaPatch, evidence: str) -> ToolResult:
    """根据用户本轮明确声明提出长期画像更新，等待独立人工接口确认.

    changes 仅允许表达偏好、投资经验、自述风险偏好、期限、目标和排除的基金类型。
    evidence 必须引用当前真实用户消息原文，不能引用助手、工具、截图或旧会话。
    仅用户明确要求记住或纠正长期偏好时调用；问询、假设和一次性需求不能当成真实画像。
    不包含持仓、金额、净值或交易授权。返回 PENDING 只表示候选，普通聊天“确认”不会生效。
    """
    runtime = get_tool_runtime()
    try:
        proposal = await user_persona_service.propose(
            runtime.user_id,
            changes,
            evidence,
            runtime.thread_id,
            runtime.user_message_id,
            runtime.user_message,
        )
    except PersonaLimitError:
        return ToolResult.fail("PROFILE_REVIEW_REQUIRED", "请先处理已有画像候选")
    except ValueError:
        return ToolResult.fail("INVALID_PROFILE_EVIDENCE", "请引用当前用户消息原文，不能推测画像")
    return ToolResult.ok(
        proposal.model_dump(mode="json"),
        source="user_persona",
        warnings=["候选尚未生效，请在画像管理界面人工确认；模型不能自行确认。"],
    )
