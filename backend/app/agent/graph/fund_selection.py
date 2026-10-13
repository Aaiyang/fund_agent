"""独立基金选择子图：先搜索并保存候选，再中断等待人工选择."""

import re
from typing import Annotated, Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, ValidationError

from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import runtime_from_config
from app.core.logging import logger
from app.schemas.fund_selection import (
    FundSelectionAction,
    FundSelectionCall,
    FundSelectionDecision,
    FundSelectionOption,
    FundSelectionResult,
)
from app.services.fund_service import fund_service

FUND_SELECTION_TOOL = "resolve_fund_for_analysis"


class FundSelectionState(BaseModel):
    """消息、本轮标识及结果与主图共享；调用、候选及身份为子图私有."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    turn_id: str = ""
    fund_selection_result: FundSelectionResult | None = None
    active_call: FundSelectionCall | None = None
    selection: FundSelectionAction | None = None
    owner_id: int | None = None


def _pending_calls(state: FundSelectionState) -> list[dict[str, Any]]:
    for index in range(len(state.messages) - 1, -1, -1):
        message = state.messages[index]
        if isinstance(message, AIMessage):
            completed = {item.tool_call_id for item in state.messages[index + 1 :] if isinstance(item, ToolMessage)}
            return [dict(call) for call in message.tool_calls if call["id"] not in completed]
    return []


def _complete(
    call: dict[str, Any] | FundSelectionCall, result: ToolResult, outcome: FundSelectionResult | None = None
) -> Command:
    if isinstance(call, FundSelectionCall):
        call = call.model_dump()
    return Command(
        update={
            "messages": [ToolMessage(content=result.to_text(), name=call["name"], tool_call_id=call["id"])],
            "active_call": None,
            "selection": None,
            "owner_id": None,
            "fund_selection_result": outcome,
        },
        goto="search",
    )


async def _search(state: FundSelectionState, config: RunnableConfig) -> Command:
    runtime = runtime_from_config(config)
    calls = _pending_calls(state)
    if not calls:
        return Command(goto=END)
    # 不执行同批次中基于猜测代码的分析。为每个延后调用补齐 ToolMessage，保持配对。
    deferred = [call for call in calls if call["name"] != FUND_SELECTION_TOOL]
    if deferred:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=ToolResult.fail(
                            "FUND_SELECTION_PENDING",
                            "请先解析基金目标，再使用已确认代码重新调用此工具。",
                            retryable=False,
                        ).to_text(),
                        name=call["name"],
                        tool_call_id=call["id"],
                    )
                    for call in deferred
                ]
            },
            goto="search",
        )
    call = calls[0]
    keyword = call.get("args", {}).get("keyword")
    if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 120:
        return _complete(call, ToolResult.fail("INVALID_KEYWORD", "请提供有效基金名称或代码。", retryable=False))
    keyword = keyword.strip()
    try:
        items = await fund_service.search_analysis_candidates(keyword)
        options: dict[str, FundSelectionOption] = {}
        for item in items:
            if re.fullmatch(r"\d{6}", item.fund_code) and item.fund_name:
                options.setdefault(
                    item.fund_code,
                    FundSelectionOption(fund_code=item.fund_code, fund_name=item.fund_name, fund_type=item.fund_type),
                )
    except Exception:
        logger.exception("fund_selection_search_failed", thread_id=runtime.thread_id)
        return _complete(call, ToolResult.fail("FUND_SEARCH_FAILED", "基金搜索暂时失败，请稍后重试。", retryable=True))
    matches = list(options.values())

    def normalize(value: str) -> str:
        return "".join(value.split()).casefold()

    exact = [item for item in matches if normalize(item.fund_name) == normalize(keyword)]
    if re.fullmatch(r"\d{6}", keyword):
        matches = [item for item in matches if item.fund_code == keyword]
    elif len(exact) == 1:
        matches = exact
    # 只有精确代码或唯一完整名称能自动解析；单个模糊候选也要人工确认。
    precise = bool(re.fullmatch(r"[0-9]{6}", keyword) or len(exact) == 1)
    if not matches or (precise and len(matches) == 1):
        return _complete(
            call,
            ToolResult.ok(
                {
                    "status": "resolved" if matches else "not_found",
                    "keyword": keyword,
                    "fund": matches[0].model_dump() if matches else None,
                },
                source="fund_service",
            ),
            FundSelectionResult(
                turn_id=state.turn_id,
                tool_call_id=call["id"],
                status="resolved" if matches else "not_found",
                keyword=keyword,
                fund=matches[0] if matches else None,
            ),
        )
    return Command(
        update={
            "active_call": FundSelectionCall.model_validate(call),
            "selection": FundSelectionAction(keyword=keyword, candidates=matches[:3]),
            "owner_id": runtime.user_id,
        },
        goto="choose",
    )


async def _choose(state: FundSelectionState, config: RunnableConfig) -> Command:
    if state.selection is None or state.active_call is None:
        return Command(goto="search")
    runtime = runtime_from_config(config)
    if runtime.user_id != state.owner_id:
        raise PermissionError("fund_selection_owner_mismatch")
    value = interrupt(state.selection.model_dump(mode="json"))
    try:
        decision = FundSelectionDecision.model_validate(value)
    except ValidationError:
        return Command(goto="choose")
    if decision.decision == "cancel":
        result = ToolResult.ok(
            {"status": "cancelled", "instruction": "用户取消选择，停止本次基金分析，请等待用户补充名称或代码。"},
            source="user_selection",
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(content=result.to_text(), name=call["name"], tool_call_id=call["id"])
                    for call in _pending_calls(state)
                ],
                "active_call": None,
                "selection": None,
                "owner_id": None,
                "fund_selection_result": FundSelectionResult(
                    turn_id=state.turn_id,
                    tool_call_id=state.active_call.id,
                    status="cancelled",
                    keyword=state.selection.keyword,
                ),
            },
            goto=END,
        )
    selected = next((item for item in state.selection.candidates if item.fund_code == decision.fund_code), None)
    if selected is None:
        return Command(goto="choose")
    return _complete(
        state.active_call,
        ToolResult.ok(
            {
                "status": "resolved",
                "keyword": state.selection.keyword,
                "fund": selected.model_dump(),
                "confirmed_by_user": True,
            },
            source="user_selection",
        ),
        FundSelectionResult(
            turn_id=state.turn_id,
            tool_call_id=state.active_call.id,
            status="resolved",
            keyword=state.selection.keyword,
            fund=selected,
            confirmed_by_user=True,
        ),
    )


def build_fund_selection_subgraph() -> CompiledStateGraph:
    """编译搜索和选择节点，继承主图 checkpointer."""
    graph = StateGraph(FundSelectionState)
    graph.add_node("search", _search, destinations=("search", "choose", END))
    graph.add_node("choose", _choose, destinations=("search", "choose"))
    graph.set_entry_point("search")
    return graph.compile(name="fund_target_selection")
