"""AgentStatus 构建器：从当前 Run 的消息中确定性生成执行状态.

第一版只表达事实（工具调用计数、重复调用、最近错误），不做 LLM 推断、
不做任务规划。AgentStatus 放在 Dynamic Tail（上下文最末尾）——它每轮
都变，放尾部不影响前面稳定内容的 KV Cache 前缀。
"""

from app.agent.context.models import AgentStatus, CurrentUserTurn


def build_agent_status(
    *,
    run_id: str | None,
    current_turn: CurrentUserTurn,
    current_turn_messages: list,
) -> AgentStatus:
    """从当前轮消息统计工具调用事实.

    Args:
        run_id: 本次运行的 ID（可选）。
        current_turn: 当前用户提问（用于 goal 上下文，第一版留空 goal）。
        current_turn_messages: 当前轮的原始消息（human + AI/Tool 轨迹）。
    """
    tool_call_count = 0
    tool_calls_by_name: dict[str, int] = {}
    signature_counts: dict[str, list[str]] = {}
    last_tool_name: str | None = None
    last_error: str | None = None

    for message in current_turn_messages:
        message_type = getattr(message, "type", None)
        if message_type == "ai":
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                if not name:
                    continue
                tool_call_count += 1
                tool_calls_by_name[name] = tool_calls_by_name.get(name, 0) + 1
                last_tool_name = name
                args = call.get("args") if isinstance(call, dict) else None
                short_args = _short_args(args)
                signature_counts.setdefault(f"{name}({short_args})", []).append(name)
        elif message_type == "tool":
            last_tool_name = getattr(message, "name", None) or last_tool_name
            content = str(getattr(message, "content", ""))
            if content.startswith("[TOOL_ERROR]"):
                last_error = content.splitlines()[0]

    duplicate_tool_calls = [signature for signature, occurrences in signature_counts.items() if len(occurrences) > 1]

    return AgentStatus(
        run_id=run_id,
        tool_call_count=tool_call_count,
        tool_calls_by_name=tool_calls_by_name,
        duplicate_tool_calls=duplicate_tool_calls,
        last_tool_name=last_tool_name,
        last_error=last_error,
        warnings=["存在重复的工具调用，请勿再次重复"] if duplicate_tool_calls else [],
    )


def _short_args(args) -> str:
    """参数的紧凑展示（截断，避免状态块膨胀）."""
    import json

    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    return text if len(text) <= 60 else text[:57] + "..."


def render_agent_status(status: AgentStatus) -> str:
    """序列化成放尾部 SystemMessage 的稳定文本（spec 41：键序稳定）."""
    import json

    lines = ["<agent_status>"]
    if status.goal:
        lines.append(f"goal: {status.goal}")
    lines.append(f"tool_call_count: {status.tool_call_count}")
    if status.tool_calls_by_name:
        lines.append("tool_calls:")
        for name in sorted(status.tool_calls_by_name):
            lines.append(f"  {name}: {status.tool_calls_by_name[name]}")
    if status.duplicate_tool_calls:
        lines.append("duplicate_warnings:")
        for item in status.duplicate_tool_calls:
            lines.append(f"  - {item}")
    if status.last_error:
        lines.append(f"last_error: {status.last_error}")
    lines.append("</agent_status>")
    # 稳定序列化兜底（spec 41）
    json.dumps(status.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True)
    return "\n".join(lines)
