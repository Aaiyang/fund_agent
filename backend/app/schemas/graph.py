"""应用的 LangGraph 状态 schema 定义."""

from typing import Annotated

from langgraph.graph.message import add_messages
from pydantic import (
    BaseModel,
    Field,
)


class GraphState(BaseModel):
    """LangGraph Agent/Workflow 的状态定义."""

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The messages in the conversation"
    )
    long_term_memory: str = Field(default="", description="The long term memory of the conversation")
    holding_import_ids: list[str] = Field(default_factory=list, description="本轮已验证用户与会话归属的截图批次")
