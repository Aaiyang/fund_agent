"""Agent 的 LangGraph 工具包.

工具集合定义在 ``registry.py``（fund / portfolio / market / system 四组）；
业务工具通过 ``runtime.py`` 读取运行时身份，用 ``result.py`` 的统一
``ToolResult`` 信封返回结果。
"""

from langchain_core.tools.base import BaseTool

from .registry import DEFAULT_AGENT_TOOLS

tools: list[BaseTool] = DEFAULT_AGENT_TOOLS

__all__ = ["tools"]
