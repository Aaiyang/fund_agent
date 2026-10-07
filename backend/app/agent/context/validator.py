"""Context 不变量校验：只检查、不偷偷修复.

任何不变量被破坏都会抛出 `ContextInvariantError`，由上层决定如何响应
（本设计的含义是：绝不带着非法上下文去调用 LLM）。
"""

from app.agent.context.models import ContextDiagnostics, ContextEnvelope, ContextInvariantError


class ContextValidator:
    """在调用 LLM 之前校验最终上下文的五条不变量（spec 21）."""

    def validate(
        self,
        messages: list,
        envelope: ContextEnvelope,
        diagnostics: ContextDiagnostics,
    ) -> None:
        """逐条校验不变量，全部通过则静默返回.

        Raises:
            ContextInvariantError: CURRENT_USER_TURN_MISSING /
                ONLY_SYSTEM_MESSAGE / CURRENT_USER_TURN_DROPPED /
                CONTEXT_BUDGET_EXCEEDED / INVALID_TOOL_TRACE。
        """
        humans = [m for m in messages if getattr(m, "type", None) == "human"]

        # 规则 1：正常请求必须存在当前用户提问
        if not envelope.current_turn.content:
            raise ContextInvariantError("CURRENT_USER_TURN_MISSING")

        # 规则 2：最终上下文不能只有 System
        if len(messages) <= 1 and not humans:
            raise ContextInvariantError(
                "ONLY_SYSTEM_MESSAGE",
                "组装结果只剩系统提示词，拒绝调用 LLM",
            )

        # 规则 3：当前用户提问必须真的出现在最终上下文里
        if not any(getattr(m, "content", None) == envelope.current_turn.content for m in humans):
            raise ContextInvariantError(
                "CURRENT_USER_TURN_DROPPED",
                "当前用户提问被上下文组装丢弃",
            )

        # 规则 4：总 token 不得超过预算
        if diagnostics.total_tokens > diagnostics.max_context_tokens:
            raise ContextInvariantError(
                "CONTEXT_BUDGET_EXCEEDED",
                f"上下文总量 {diagnostics.total_tokens} 超过预算 {diagnostics.max_context_tokens}",
            )

        # 规则 5：AI ToolCall 与 ToolMessage 的配对必须完整
        pending_tool_calls: set[str] = set()
        for message in messages:
            message_type = getattr(message, "type", None)
            if message_type == "ai":
                for tool_call in getattr(message, "tool_calls", None) or []:
                    call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
                    if call_id:
                        pending_tool_calls.add(call_id)
            elif message_type == "tool":
                call_id = getattr(message, "tool_call_id", None)
                if call_id not in pending_tool_calls:
                    raise ContextInvariantError(
                        "INVALID_TOOL_TRACE",
                        "存在没有对应 AI ToolCall 的孤立 ToolMessage",
                    )
                pending_tool_calls.discard(call_id)
        if pending_tool_calls:
            raise ContextInvariantError(
                "INVALID_TOOL_TRACE",
                f"存在未收到结果的 AI ToolCall：{sorted(pending_tool_calls)}",
            )


context_validator = ContextValidator()
