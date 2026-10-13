"""悬空 AI ToolCall 的确定性补齐.

chat 节点写完「带 tool_calls 的 AIMessage」就落 checkpoint；若 tool_call 节点
没跑完（客户端断连、发版重启、进程被 OOM 打死），checkpoint 里就留下没有配对
ToolMessage 的 AI ToolCall。校验器规则 5 会因此拒绝每一次后续提问，会话永久
不可用。这里在组装提示词前补齐配对：只补不改写，历史顺序与 KV Cache 前缀
保持不动，模型据此知道这项结果并未真的取到。
"""

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

# 与 ToolResult.fail("RUN_INTERRUPTED", ...).to_text() 同格式。这里不 import tools 层：
# tools/__init__ 会拉起全部工具与服务，context 反向依赖它就是循环导入。
_REPAIR_CONTENT = (
    "[TOOL_ERROR] RUN_INTERRUPTED: 上一轮在该工具执行完成前中断，结果未获取；"
    "不能据此推断，需要时请重新调用。 retryable=true"
)


def repair_unresolved_tool_calls(messages: list[Any]) -> tuple[list[Any], int]:
    """为没有对应 ToolMessage 的 AI ToolCall 补一条中断失败结果.

    Args:
        messages: 会话消息列表（不含系统提示词）。

    Returns:
        (补齐后的消息列表, 补入条数)。原列表无悬空调用时返回同一个列表对象。
    """
    resolved = {
        message.tool_call_id for message in messages if isinstance(message, ToolMessage) and message.tool_call_id
    }
    if not any(
        isinstance(message, AIMessage)
        and any(call.get("id") and call["id"] not in resolved for call in message.tool_calls)
        for message in messages
    ):
        return messages, 0

    repaired: list[Any] = []
    added = 0
    for message in messages:
        repaired.append(message)
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        for call in message.tool_calls:
            call_id = call.get("id")
            if not call_id or call_id in resolved:
                continue
            repaired.append(
                ToolMessage(
                    content=_REPAIR_CONTENT,
                    name=call.get("name") or "unknown",
                    tool_call_id=call_id,
                )
            )
            resolved.add(call_id)
            added += 1
    return repaired, added
