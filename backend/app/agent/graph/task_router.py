"""主图任务路由：校验研究请求、顺序解析对象，人工中断由既有入口恢复."""

import re
import json
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import Command
from pydantic import ValidationError

from app.agent.context import extract_text_content
from app.agent.tools.result import ToolResult
from app.schemas.graph import GraphState
from app.schemas.research import DEEP_RESEARCH_INTENTS, ResearchRequest, ResearchResult, ResearchTask
from app.utils.task_routing import (
    explicitly_supplied_operation_amount,
    explicit_multi_role_research,
    infer_research_request,
    request_after_fund_selection,
)
from app.schemas.fund_selection import FundSelectionOption
from app.core.logging import logger


def route_task(state: GraphState) -> Command:
    """规则明确的请求直接执行；其他自然语言复用chat首次调用提出start_research."""
    trusted = getattr(state, "research_task", None)
    # 服务端授权的两种入口：报告按钮（followup）与基金页的多智能体按钮（client）。
    # 模型自己提出的 start_research 仍要逐字段过本轮原文取证。
    if trusted is not None and trusted.requested_by != "model" and trusted.turn_id == state.turn_id:
        return Command(goto="continue_research")
    last = state.messages[-1] if state.messages else None
    request = None
    updates: dict = {}
    user = next((message for message in reversed(state.messages) if isinstance(message, HumanMessage)), None)
    instruction = extract_text_content(user.content) if user else ""
    if isinstance(last, AIMessage):
        calls = [call for call in last.tool_calls if call["name"] == "start_research"]
        if not calls:
            return Command(goto="chat")
        try:
            if len(calls) != 1:
                raise ValueError("一次只启动一个研究任务，请将复合任务按顺序处理")
            request = ResearchRequest.model_validate(calls[0]["args"])
            if request.strategy == "multi_role" and not explicit_multi_role_research(instruction):
                raise ValueError("多角色研究需要用户明确请求或通过报告按钮启动")
            normalized = "".join(instruction.split()).casefold()
            confirmed = state.fund_selection_result
            if request.sector_query and "".join(request.sector_query.split()).casefold() not in normalized:
                raise ValueError("板块查询词必须来自本轮用户原文，不猜BK代码")
            if request.stock_symbol and not re.search(
                rf"(?<![A-Za-z0-9.]){re.escape(request.stock_symbol)}(?![A-Za-z0-9.])", instruction
            ):
                raise ValueError("股票市场和代码必须由本轮用户明确提供，不能根据名称猜测")
            confirmed_fund = (
                confirmed.fund
                if confirmed is not None and confirmed.turn_id == state.turn_id and confirmed.status == "resolved"
                else None
            )
            for query in request.fund_queries:
                supplied = (
                    bool(re.search(rf"(?<!\d){re.escape(query)}(?!\d)", instruction))
                    if re.fullmatch(r"\d{6}", query)
                    else "".join(query.split()).casefold() in normalized
                )
                already_resolved = confirmed_fund is not None and query in {
                    confirmed_fund.fund_code,
                    confirmed_fund.fund_name,
                }
                if not supplied and not already_resolved:
                    raise ValueError("基金查询词必须来自本轮用户原文或已确认对象，不猜完整名称、代码或份额")
            if request.account_id is not None and not re.search(
                rf"(?:账户|账号)\s*(?:ID|id|编号)?\s*[：:#]?\s*{request.account_id}(?!\d)", instruction
            ):
                raise ValueError("本轮用户未明确指定该账户编号，请澄清账户范围，不猜测或默认替换编号")
            if request.proposed_amount is not None and not explicitly_supplied_operation_amount(
                instruction, request.proposed_amount
            ):
                raise ValueError("拟操作金额须在本轮用户消息中明确给出元或万元，不推测金额")
            responses = [
                ToolMessage(
                    content=ToolResult.ok(
                        {"status": "routing", "intent": request.intent}, source="task_router"
                    ).to_text()
                    if call["name"] == "start_research"
                    else ToolResult.fail(
                        "RESEARCH_PENDING", "先完成研究任务；其他请求需在完成后重新提出工具调用"
                    ).to_text(),
                    name=call["name"],
                    tool_call_id=call["id"],
                )
                for call in last.tool_calls
            ]
            updates["messages"] = responses
        except (ValidationError, ValueError) as exc:
            # 校验错误不回传包含原始载荷的Pydantic堆栈。
            notice = (
                str(exc)
                if not isinstance(exc, ValidationError)
                else "请提供有效的研究类型、基金查询词和范围，不传身份或交易参数。"
            )
            logger.info("research_request_rejected", turn_id=state.turn_id, reason=notice)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=ToolResult.fail("INVALID_RESEARCH_REQUEST", notice).to_text(),
                            name=call["name"],
                            tool_call_id=call["id"],
                        )
                        for call in last.tool_calls
                    ]
                },
                goto="chat",
            )
    elif isinstance(last, HumanMessage) and not state.holding_import_ids:
        # 带图问题先由chat确认是图片分析、已登记持仓诊断还是导入，不用文本规则猜范围。
        request = infer_research_request(instruction)
    if request is None:
        return Command(goto="chat")
    if request.strategy == "multi_role":
        request = request.model_copy(update={"mode": "deep"})
    resolved = []
    confirmed = state.fund_selection_result
    if confirmed is not None and confirmed.turn_id == state.turn_id and confirmed.fund is not None:
        for query in request.fund_queries:
            if query not in {confirmed.keyword, confirmed.fund.fund_code, confirmed.fund.fund_name}:
                break
            resolved.append(confirmed.fund)
    task = ResearchTask(turn_id=state.turn_id, request=request, instruction=instruction, resolved_funds=resolved)
    updates.update({"research_task": task, "research_result": None})
    return Command(update=updates, goto="continue_research")


def continue_research(state: GraphState) -> Command:
    """恢复本轮基金选择后继续同一研究；旧选择结果不得污染新任务."""
    task = state.research_task
    if task is None:
        task = _research_after_selection(state)
    if task is None or task.turn_id != state.turn_id:
        return Command(goto="chat")
    queries = task.request.fund_queries
    outcome = state.fund_selection_result
    resolved = list(task.resolved_funds)
    next_index = len(resolved)
    last = state.messages[-1] if state.messages else None
    if (
        next_index < len(queries)
        and isinstance(last, ToolMessage)
        and last.name == "resolve_fund_for_analysis"
        and (outcome is None or outcome.turn_id != state.turn_id or outcome.keyword != queries[next_index])
    ):
        # 搜索故障不重新进入解析循环，也不能把上一个对象的结果用于当前对象。
        notice = "基金目标暂时无法核验，本次研究已停止。请稍后重试或提供准确的基金名称、代码。"
        return Command(
            update={
                "messages": [AIMessage(content=notice)],
                "research_result": ResearchResult(
                    turn_id=state.turn_id,
                    intent=task.request.intent,
                    status="needs_input",
                    fund_codes=[fund.fund_code for fund in resolved],
                    gaps=["基金目标解析失败，未进行研究取证"],
                ),
            },
            goto=END,
        )
    if (
        next_index < len(queries)
        and outcome is not None
        and outcome.turn_id == state.turn_id
        and outcome.keyword == queries[next_index]
    ):
        if outcome.status in {"cancelled", "not_found"}:
            return Command(goto="chat")
        if outcome.fund is not None:
            resolved.append(outcome.fund)
    task = task.model_copy(update={"resolved_funds": resolved})
    if len(resolved) < len(queries):
        call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "resolve_fund_for_analysis",
                    "args": {"keyword": queries[len(resolved)]},
                    "id": uuid4().hex,
                }
            ],
        )
        return Command(update={"research_task": task, "messages": [call]}, goto="fund_selection")
    return Command(update={"research_task": task}, goto=_chain_node(task))


def _chain_node(task: ResearchTask) -> str:
    """路由这一刻就决定走哪条研究链：单档走共用子图，多智能体走它自己的独立链路.

    以前两条链共用一个子图，策略判断埋在取证之后，于是 skill/取证/报告模板全是共用的，
    "多智能体"实际只剩同一份证据包上的三次并行摘要。板块与个股不支持该档位（schema 已拦），
    这里再兜一次，避免路由到不存在的节点。
    """
    if task.request.strategy == "multi_role" and task.request.intent in DEEP_RESEARCH_INTENTS:
        return "deep_" + task.request.intent
    return task.request.intent


def _research_after_selection(state: GraphState) -> ResearchTask | None:
    """兼容直接resolve工具与旧检查点：保留原问题，复用同批真实确认对象."""
    outcome = state.fund_selection_result
    if outcome is None or outcome.turn_id != state.turn_id or outcome.status != "resolved":
        return None
    user_index = next(
        (index for index in range(len(state.messages) - 1, -1, -1) if isinstance(state.messages[index], HumanMessage)),
        None,
    )
    if user_index is None:
        return None
    batch_index = next(
        (
            index
            for index in range(len(state.messages) - 1, user_index, -1)
            if isinstance(state.messages[index], AIMessage)
        ),
        None,
    )
    if batch_index is None:
        return None
    calls = [call for call in state.messages[batch_index].tool_calls if call["name"] == "resolve_fund_for_analysis"]
    if outcome.tool_call_id not in {call["id"] for call in calls}:
        return None
    outputs = {
        item.tool_call_id: item
        for item in state.messages[batch_index + 1 :]
        if isinstance(item, ToolMessage) and item.name == "resolve_fund_for_analysis"
    }
    funds = []
    for call in calls:
        item = outputs.get(call["id"])
        try:
            data = json.loads(extract_text_content(item.content).splitlines()[1]) if item else {}
            if data.get("status") != "resolved":
                return None
            funds.append(FundSelectionOption.model_validate(data["fund"]))
        except (ValueError, IndexError, KeyError):
            return None
    instruction = extract_text_content(state.messages[user_index].content)
    request = request_after_fund_selection(instruction, [fund.fund_code for fund in funds])
    if request is None:
        return None
    return ResearchTask(turn_id=state.turn_id, request=request, instruction=instruction, resolved_funds=funds)
