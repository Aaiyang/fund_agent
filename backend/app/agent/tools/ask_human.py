"""LangGraph 的人工确认（HITL）工具.

在执行敏感动作之前，暂停图的运行，向用户征求确认。
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_human(question: str) -> str:
    """暂停执行并向用户提出问题，等待确认.

    在执行敏感或不可撤销的操作（例如删除数据、发送邮件、下单购买等）
    之前，需要用户澄清、确认或补充信息时，使用本工具。

    Args:
        question: 要向用户提出的问题。

    Returns:
        str: 用户的答复。
    """
    user_response = interrupt(question)
    return str(user_response)
