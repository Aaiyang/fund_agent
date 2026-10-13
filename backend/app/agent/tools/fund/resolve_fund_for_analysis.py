"""声明基金分析目标解析意图，由图节点负责搜索和人工选择."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.result import ToolResult


@tool
async def resolve_fund_for_analysis(
    keyword: Annotated[str, Field(min_length=1, max_length=120, description="用户提供的基金名称、简称或代码")],
) -> str:
    """分析基金前解析用户给出的名称，存在歧义时暂停并让用户选择前三个候选.

    使用完整名册做模糊匹配，按名称相似度排序、按代码去重后返回最多三个候选。
    模糊候选即使只有一个也需要用户确认；唯一完整名称准确匹配才直接返回。
    不要并行调用依赖该基金代码的工具。
    用户已明确提供六位代码或已选定基金时无需调用。
    """
    return ToolResult.fail(
        "FUND_SELECTION_REQUIRES_GRAPH", "基金目标解析必须通过 fund_selection 图节点执行。", retryable=False
    ).to_text()
