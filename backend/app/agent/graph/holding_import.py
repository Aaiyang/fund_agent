"""截图导入子图：等待识别 → 补充账户 → 人工复核 → 核验结果，子图没有持仓写入口."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.agent.tools.guard import DuplicateToolGuard, build_tool_signature, count_signature_occurrences
from app.agent.tools.portfolio.holding_import import get_holding_import
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import ToolRuntimeError, runtime_from_config, set_tool_runtime
from app.core.config import settings
from app.core.logging import logger
from app.schemas.graph import GraphState
from app.schemas.agent_import import HoldingImportAccountSelection, HoldingImportProcessing
from app.schemas.holding_import_graph import (
    HoldingImportAccountValue,
    HoldingImportCall,
    HoldingImportContinueValue,
    HoldingImportDecisionValue,
    HoldingImportGraphState,
    HoldingImportToolArgs,
)
from app.services.agent_holding_import_service import agent_holding_import_service
from app.services.holding_import_service import ImportStateError
from app.utils.screenshot_errors import screenshot_failure_message

HOLDING_IMPORT_TOOL_NAMES = frozenset({"get_holding_import", "request_holding_import_confirmation"})


def _latest_tool_message(state: GraphState | HoldingImportGraphState) -> tuple[int, AIMessage]:
    """定位此次模型批次，不把之前的工具请求当作新的截图任务."""
    for index in range(len(state.messages) - 1, -1, -1):
        message = state.messages[index]
        if isinstance(message, AIMessage):
            if message.tool_calls:
                return index, message
            break
    raise ValueError("holding_import_requires_ai_tool_calls")


def _complete(call: Mapping[str, Any], content: str) -> Command:
    """每个原始 ToolCall 恰好补一条结果，继续处理本批次未完成的图片任务."""
    return Command(
        update={
            "messages": [ToolMessage(content=content, name=call["name"], tool_call_id=call["id"])],
            "active_call": None,
            "review": None,
            "decision": None,
            "resolved_account_id": None,
            "resolved_import_id": None,
        },
        goto="load_draft",
    )


async def _load_draft(state: HoldingImportGraphState, config: RunnableConfig) -> Command:
    """顺序处理图片批次，识别未完成时中断等待，恢复不重复启动任务."""
    index, message = _latest_tool_message(state)
    completed = {m.tool_call_id for m in state.messages[index + 1 :] if isinstance(m, ToolMessage)}
    call = next(
        (
            call
            for call in message.tool_calls
            if call["name"] in HOLDING_IMPORT_TOOL_NAMES and call["id"] not in completed
        ),
        None,
    )
    if call is None:
        return Command(
            update={
                "active_call": None,
                "review": None,
                "decision": None,
                "holding_import_ids": [],
                "holding_account_id": None,
                "holding_instruction": "",
                "resolved_account_id": None,
                "resolved_import_id": None,
            },
            goto=END,
        )
    call_id = call["id"]
    if not call_id:
        raise ValueError("holding_import_tool_call_id_missing")

    history = state.messages[:index]
    last_user = max((i for i, m in enumerate(history) if getattr(m, "type", None) == "human"), default=-1)
    guard = DuplicateToolGuard(settings.DUPLICATE_TOOL_MAX_SAME_CALLS, settings.DUPLICATE_TOOL_GUARD_ENABLED)
    if guard.should_block(
        count_signature_occurrences(history[last_user + 1 :], build_tool_signature(call["name"], call["args"]))
    ):
        return _complete(
            call, ToolResult.fail("DUPLICATE_TOOL_CALL", "请复用本轮已有结果，不要重复查询截图批次").to_text()
        )
    try:
        arguments = HoldingImportToolArgs.model_validate(call["args"])
        runtime = runtime_from_config(config)
        set_tool_runtime(runtime)
        if call["name"] == "get_holding_import":
            result = await get_holding_import.ainvoke(arguments.model_dump())
            return _complete(call, str(result))
        detail = await agent_holding_import_service.detail(runtime.user_id, runtime.thread_id, arguments.import_id)
        if detail.status in {"APPLIED", "CANCELLED"}:
            return _complete(call, ToolResult.ok({"import_id": detail.id, "status": detail.status}).to_text())
        active = HoldingImportCall(
            call_id=call_id, name="request_holding_import_confirmation", import_id=arguments.import_id
        )
        if detail.status == "UPLOADED":
            if arguments.import_id not in state.holding_import_ids:
                return _complete(
                    call,
                    ToolResult.fail(
                        "IMPORT_IMAGE_REQUIRED", "请将持仓截图随本轮导入问题一起上传，不能使用历史批次启动新的导入。"
                    ).to_text(),
                )
            # 附件只有随问题进入子图才开始识别，重复恢复不会重新入队。
            await agent_holding_import_service.start(runtime.user_id, runtime.thread_id, arguments.import_id)
            detail = await agent_holding_import_service.detail(runtime.user_id, runtime.thread_id, arguments.import_id)
        if detail.status in {"UPLOADED", "PARSING"}:
            return Command(
                update={
                    "active_call": active,
                    "review": HoldingImportProcessing(import_id=arguments.import_id),
                    "decision": None,
                },
                goto="wait_processing",
            )
        if detail.status != "REVIEW_REQUIRED":
            code, notice = screenshot_failure_message(detail.error_message)
            return _complete(
                call,
                ToolResult.fail(code, notice).to_text(),
            )
        destination = (
            state.resolved_account_id
            if state.resolved_import_id == arguments.import_id
            else (
                await agent_holding_import_service.resolve_account(
                    runtime.user_id, state.holding_instruction, state.holding_account_id
                )
                if state.holding_instruction or state.holding_account_id is not None
                else None
            )
        )
        if destination is not None and destination != detail.account_id:
            await agent_holding_import_service.select_account(
                runtime.user_id, runtime.thread_id, arguments.import_id, destination
            )
            detail = await agent_holding_import_service.detail(runtime.user_id, runtime.thread_id, arguments.import_id)
        if detail.account_id is None:
            accounts = await agent_holding_import_service.accounts(runtime.user_id)
            notice = (
                "截图已识别，请选择要同步到的持仓账户，再核对识别结果。"
                if accounts
                else "截图已识别，但你还没有持仓账户。请先创建账户，再返回选择目标。"
            )
            return Command(
                update={
                    "active_call": active,
                    "review": HoldingImportAccountSelection(
                        import_id=arguments.import_id, accounts=accounts, notice=notice
                    ),
                    "decision": None,
                },
                goto="choose_account",
            )
        review = await agent_holding_import_service.review(runtime.user_id, runtime.thread_id, arguments.import_id)
    except ValidationError:
        return _complete(call, ToolResult.fail("INVALID_ARGUMENT", "只接受有效的截图批次号import_id").to_text())
    except ToolRuntimeError as exc:
        return _complete(call, ToolResult.fail(exc.code, exc.message).to_text())
    except ImportStateError:
        return _complete(call, ToolResult.fail("IMPORT_NOT_READY", "当前会话没有可复核的截图批次").to_text())
    except Exception:
        logger.exception("holding_import_subgraph_load_failed", tool_call_id=call["id"])
        return _complete(
            call, ToolResult.fail("UPSTREAM_ERROR", "读取截图草稿失败，请稍后重试", retryable=True).to_text()
        )

    logger.info("holding_import_subgraph_review_ready", import_id=review.import_id, session_id=runtime.thread_id)
    return Command(
        update={
            "active_call": HoldingImportCall(
                call_id=call_id, name="request_holding_import_confirmation", import_id=arguments.import_id
            ),
            "review": review,
            "decision": None,
        },
        goto="human_review",
    )


async def _human_review(state: HoldingImportGraphState) -> dict[str, Any]:
    """独立中断节点；恢复只重进这个节点，不重复执行先前取数和其他工具."""
    if state.review is None or state.active_call is None:
        raise ValueError("holding_import_review_state_missing")
    return {"decision": interrupt(state.review.model_dump(mode="json"))}


async def _after_processing(state: HoldingImportGraphState) -> Command:
    """恢复只重新读取持久化识别状态，不让主图猜测识别结果."""
    if (
        state.active_call is None
        or not (
            isinstance(state.decision, HoldingImportContinueValue)
            or isinstance(state.decision, HoldingImportDecisionValue)
            and state.decision.decision == "cancel"
        )
        or state.decision.import_id != state.active_call.import_id
    ):
        return Command(update={"decision": None}, goto="wait_processing")
    return Command(update={"review": None, "decision": None}, goto="load_draft")


async def _apply_account_selection(state: HoldingImportGraphState, config: RunnableConfig) -> Command:
    """账户选择只绑定草稿，随后重新生成真实复核卡及指纹."""
    active = state.active_call
    if active is None:
        raise ValueError("holding_import_call_state_missing")
    runtime = runtime_from_config(config)
    detail = await agent_holding_import_service.detail(runtime.user_id, runtime.thread_id, active.import_id)
    if detail.status == "CANCELLED":
        return Command(update={"review": None, "decision": None}, goto="load_draft")
    decision = state.decision
    if isinstance(decision, HoldingImportAccountValue) and decision.import_id == active.import_id:
        await agent_holding_import_service.select_account(
            runtime.user_id, runtime.thread_id, active.import_id, decision.account_id
        )
        return Command(
            update={
                "resolved_account_id": decision.account_id,
                "resolved_import_id": active.import_id,
                "review": None,
                "decision": None,
            },
            goto="load_draft",
        )
    return Command(update={"review": None, "decision": None}, goto="load_draft")


async def _read_result(state: HoldingImportGraphState, config: RunnableConfig) -> Command:
    """人工 HTTP 端点负责写入，这里只核验数据库中的真实终态."""
    active = state.active_call
    if active is None:
        raise ValueError("holding_import_call_state_missing")
    call = {"id": active.call_id, "name": active.name}
    try:
        runtime = runtime_from_config(config)
        detail = await agent_holding_import_service.detail(runtime.user_id, runtime.thread_id, active.import_id)
    except ToolRuntimeError as exc:
        return _complete(call, ToolResult.fail(exc.code, exc.message).to_text())
    except ImportStateError:
        return _complete(call, ToolResult.fail("IMPORT_NOT_FOUND", "当前会话没有该截图批次").to_text())
    except Exception:
        logger.exception("holding_import_subgraph_result_failed", import_id=active.import_id)
        return _complete(
            call, ToolResult.fail("UPSTREAM_ERROR", "读取人工决策结果失败，请查询导入状态", retryable=True).to_text()
        )

    decision = state.decision
    valid = isinstance(decision, HoldingImportDecisionValue) and decision.import_id == active.import_id
    action = decision.decision if isinstance(decision, HoldingImportDecisionValue) and valid else None
    expected = {"confirm": "APPLIED", "cancel": "CANCELLED"}.get(action) if isinstance(action, str) else None
    if expected is None or detail.status != expected:
        if detail.status == "REVIEW_REQUIRED":
            # 直接调用图或聊天中的“确认”不是人工端点授权，保留复核机会。
            return Command(update={"decision": None}, goto="load_draft")
        return _complete(
            call, ToolResult.fail("CONFIRMATION_REQUIRED", "人工决策与批次状态不一致，请核对导入状态").to_text()
        )

    logger.info("holding_import_subgraph_finished", import_id=active.import_id, status=detail.status)
    return _complete(
        call,
        ToolResult.ok(
            {"import_id": active.import_id, "status": detail.status, "applied": detail.items_confirmed},
            source="holding_import",
        ).to_text(),
    )


def build_holding_import_subgraph(
    execute_tools: Callable[[GraphState, RunnableConfig], Awaitable[Command]],
) -> CompiledStateGraph:
    """编译可直接挂到父图的子图，自动继承父图 checkpointer 与 tracing 配置."""

    async def prepare_tools(state: HoldingImportGraphState, config: RunnableConfig) -> dict[str, Any]:
        """先完成同批其他工具，单独 checkpoint 后再进入图片中断节点."""
        index, message = _latest_tool_message(state)
        calls = [call for call in message.tool_calls if call["name"] not in HOLDING_IMPORT_TOOL_NAMES]
        if not calls:
            return {"active_call": None, "review": None, "decision": None}
        filtered = message.model_copy(update={"tool_calls": calls})
        tools_state = GraphState(messages=[*state.messages[:index], filtered])
        command = await execute_tools(tools_state, config)
        return {**(command.update or {}), "active_call": None, "review": None, "decision": None}

    graph = StateGraph(HoldingImportGraphState)
    graph.add_node("prepare_tools", prepare_tools)
    graph.add_node(
        "load_draft",
        _load_draft,
        destinations=("load_draft", "human_review", "wait_processing", "choose_account", END),
    )
    graph.add_node("human_review", _human_review)
    graph.add_node("wait_processing", _human_review)
    graph.add_node("after_processing", _after_processing, destinations=("load_draft", "wait_processing"))
    graph.add_node("choose_account", _human_review)
    graph.add_node("apply_account_selection", _apply_account_selection, destinations=("load_draft",))
    graph.add_node("read_result", _read_result, destinations=("load_draft",))
    graph.set_entry_point("prepare_tools")
    graph.add_edge("prepare_tools", "load_draft")
    graph.add_edge("human_review", "read_result")
    graph.add_edge("wait_processing", "after_processing")
    graph.add_edge("choose_account", "apply_account_selection")
    return graph.compile(name="holding_screenshot_import")
