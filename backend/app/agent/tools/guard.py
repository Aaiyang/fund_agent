"""Duplicate Tool Guard：在工具真正执行之前识别并阻止当前 Run 内的重复调用.

层次（任务书 §12）：LLM ToolCall → DuplicateToolGuard → Tool Executor。
ContextManager 处理"已存在的上下文"，Guard 处理"即将发生的调用"——
优先在执行前阻止，而不是事后删除历史 ToolMessage。
"""

import hashlib
import json


def build_tool_signature(tool_name: str, arguments: dict) -> str:
    """工具名 + canonical 参数的稳定指纹（spec 14：sort_keys + 紧凑 JSON）."""
    normalized = json.dumps(
        arguments if isinstance(arguments, dict) else {},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(f"{tool_name}:{normalized}".encode("utf-8")).hexdigest()


def count_signature_occurrences(messages: list, signature: str, *, exclude_last_ai: bool = False) -> int:
    """统计历史消息中同一签名的工具调用次数.

    Args:
        messages: 参与统计的消息（调用方传入时排除持有当前调用的 AIMessage）。
        signature: build_tool_signature 产出的指纹。
        exclude_last_ai: 是否跳过最后一条 AI 消息（它持有的是本次调用）。
    """
    scoped = (
        messages[:-1] if exclude_last_ai and messages and getattr(messages[-1], "type", None) == "ai" else messages
    )
    count = 0
    for message in scoped:
        if getattr(message, "type", None) != "ai":
            continue
        for call in getattr(message, "tool_calls", None) or []:
            call_name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            call_args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
            if build_tool_signature(call_name or "", call_args or {}) == signature:
                count += 1
    return count


class DuplicateToolGuard:
    """执行前的重复调用守卫.

    策略（spec 15）：同一签名前 2 次放行（第 2 次记录 warning），
    第 3 次起阻止执行。阻止时返回结构化错误，由调用方包装成
    ToolMessage 回给模型——不抛 500。
    """

    def __init__(self, max_same_calls: int = 2, enabled: bool = True) -> None:
        """注入上限与开关."""
        self.max_same_calls = max_same_calls
        self.enabled = enabled

    def should_block(self, prior_count: int) -> bool:
        """prior_count 为本次调用之前已执行的同签名次数，≥ 上限则阻止."""
        return self.enabled and prior_count >= self.max_same_calls
