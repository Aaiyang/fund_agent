"""应用的 LangGraph 状态 schema 定义."""

from typing import Annotated

from langgraph.graph.message import add_messages
from pydantic import (
    BaseModel,
    Field,
)

from app.schemas.fund_selection import FundSelectionResult
from app.schemas.research import ResearchResult, ResearchTask


class GraphState(BaseModel):
    """LangGraph Agent/Workflow 的状态定义."""

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The messages in the conversation"
    )
    long_term_memory: str = Field(default="", description="The long term memory of the conversation")
    turn_id: str = Field(default="", description="新提问生成一次，人工恢复沿用的本轮标识")
    fund_selection_result: FundSelectionResult | None = None
    holding_import_ids: list[str] = Field(default_factory=list, description="本轮已验证用户与会话归属的截图批次")
    holding_account_id: int | None = None
    holding_instruction: str = ""
    research_task: ResearchTask | None = None
    research_result: ResearchResult | None = None
    memory_write_status: str | None = None
