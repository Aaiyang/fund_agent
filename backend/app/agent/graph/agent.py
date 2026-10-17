"""Agent 图与 LLM 交互的实现：chat / tool_call 节点、检查点与会话管理."""

import asyncio
import json
import time
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import replace
from typing import (
    Any,
    AsyncGenerator,
    Literal,
    Optional,
    cast,
)
from urllib.parse import quote_plus
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphInterrupt, GraphRecursionError
from langgraph.graph import (
    END,
    StateGraph,
)
from langchain_core.runnables.config import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph.state import (
    Command,
    CompiledStateGraph,
)
from langgraph.types import (
    RetryPolicy,
    StateSnapshot,
)
from psycopg import (
    AsyncConnection,
    sql,
)
from psycopg.rows import (
    DictRow,
    dict_row,
)
from psycopg_pool import AsyncConnectionPool
from pydantic import TypeAdapter
from pydantic import BaseModel

from app.core.config import settings
from app.agent.graph.fund_selection import FUND_SELECTION_TOOL, build_fund_selection_subgraph
from app.agent.graph.holding_import import HOLDING_IMPORT_TOOL_NAMES, build_holding_import_subgraph
from app.agent.graph.research import build_deep_research_subgraph, build_research_subgraph
from app.agent.graph.report_generation import generate_research_report
from app.agent.graph.research_followup import completed_followup, research_source, validate_research_followup
from app.agent.graph.task_router import continue_research, route_task
from app.agent.tools import tools
from app.agent.tools.guard import DuplicateToolGuard, build_tool_signature, count_signature_occurrences
from app.agent.tools.result import ToolResult
from app.agent.tools.runtime import ToolRuntimeError, runtime_from_config, set_tool_runtime
from app.core.logging import logger
from app.core.metrics import llm_inference_duration_seconds
from app.core.observability import langfuse_callback_handler
from app.agent.prompts import load_system_prompt
from app.schemas import (
    GraphState,
    Message,
)
from app.schemas.agent_import import AgentPendingAction, HoldingImportAccountSelection
from app.schemas.agent_resume import AgentContinueRequest, AgentRunContinuation
from app.schemas.fund_selection import FundSelectionAction, FundSelectionDecision
from app.schemas.human_question import HumanQuestionAction
from app.schemas.research import DEEP_RESEARCH_INTENTS, RESEARCH_INTENTS, ResearchGraphState, ResearchTask
from app.schemas.multi_role_research import ResearchActivity, ResearchProgress
from app.services.agent_holding_import_service import agent_holding_import_service
from app.utils.clock import business_now, trading_session_label
from app.utils.task_routing import client_research_request
from app.agent.prompts import SYSTEM_PROMPT_VERSION
from app.agent.tools.registry import TOOLS_VERSION
from app.core.metrics import (
    llm_cache_hit_ratio,
    llm_prompt_cache_hit_tokens,
    llm_prompt_cache_miss_tokens,
)
from app.services.llm import llm_service
from app.services.llm.timeouts import LLMContractViolation
from app.services.memory import memory_service
from app.services.user_persona_service import user_persona_service
from app.agent.context import (
    context_manager,
    dump_messages,
    extract_text_content,
    prepare_messages,
    process_llm_response,
)
from app.agent.context.models import ContextRequest, SessionSnapshot

PostgresConnPool = AsyncConnectionPool[AsyncConnection[DictRow]]

# 超步上限取自 settings.AGENT_RECURSION_LIMIT：父图与作为节点挂上的嵌套子图共用
# 同一份预算，多角色深研究一步就吃掉十几步，所以运行时读取而不是写死常量。
# 在工具内部调用 interrupt()、会让本超步写入全部作废的工具。它们不能与别的工具
# 同批执行，否则 resume 会把同批调用重放一遍。
# 结构化输出不合契约时，把字段错误回喂给模型的机会次数（含首次）。
_RESEARCH_CONTRACT_ATTEMPTS = 2

_INTERRUPTING_TOOLS = frozenset({"ask_human"})
_HOLDING_ACTION = TypeAdapter(AgentPendingAction)


class LangGraphAgent:
    """管理 LangGraph Agent 工作流及其与 LLM 的交互.

    负责工作流的创建与管理，包括 LLM 调用、数据库连接和响应处理。
    """

    def __init__(self):
        """初始化 LangGraph Agent 所需的组件."""
        # 使用绑定工具后的 LLM 服务
        self.llm_service = llm_service
        self.llm_service.bind_tools(tools)
        # 由图层注入，避免 context → services → database → context 的循环导入。
        context_manager.summary_manager.llm_call = self.llm_service.call
        self.tools_by_name = {tool.name: tool for tool in tools}
        # KV Cache：工具 Schema 固定且只构建一次（进入全局前缀指纹）
        self._tool_schemas = [convert_to_openai_tool(tool) for tool in tools]
        # 兼容清理旧进程内快照；新检索只进入动态尾部，不再冻结。
        self._memory_snapshots: dict[str, str] = {}
        # Duplicate Tool Guard：执行前阻止当前 Run 内的同参数重复调用
        self._tool_guard = DuplicateToolGuard(
            max_same_calls=settings.DUPLICATE_TOOL_MAX_SAME_CALLS,
            enabled=settings.DUPLICATE_TOOL_GUARD_ENABLED,
        )
        self._connection_pool: Optional[PostgresConnPool] = None
        self._graph: Optional[CompiledStateGraph] = None
        logger.info(
            "langgraph_agent_initialized",
            model=settings.DEFAULT_LLM_MODEL,
            environment=settings.ENVIRONMENT.value,
        )

    async def _get_connection_pool(self) -> PostgresConnPool:
        """按环境配置创建 PostgreSQL 连接池.

        Returns:
            AsyncConnectionPool: 已打开的连接池。

        Raises:
            Exception: 任何环境下创建失败都会抛出。
        """
        if self._connection_pool is None:
            try:
                # 按环境配置连接池大小
                max_size = settings.POSTGRES_POOL_SIZE

                connection_url = (
                    "postgresql://"
                    f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
                    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
                )

                self._connection_pool = AsyncConnectionPool(
                    connection_url,
                    open=False,
                    max_size=max_size,
                    kwargs={
                        "autocommit": True,
                        "connect_timeout": 5,
                        "prepare_threshold": None,
                        "row_factory": dict_row,
                    },
                )
                await self._connection_pool.open()
                logger.info("connection_pool_created", max_size=max_size, environment=settings.ENVIRONMENT.value)
            except Exception as e:
                logger.exception(
                    "connection_pool_creation_failed", error=str(e), environment=settings.ENVIRONMENT.value
                )
                # 不允许静默降级：checkpoint 是会话历史与人工确认（HITL）
                # 恢复状态的唯一存储。缺少它宁可让服务暴露故障，
                # 也不能悄悄丢失数据。
                raise e
        return self._connection_pool

    async def _chat(
        self, state: GraphState, config: RunnableConfig, *, research_context: str = "", final_report: bool = False
    ) -> Command:
        """处理对话状态并生成模型响应.

        Args:
            state (GraphState): 当前对话状态。
            config (RunnableConfig): 本次调用的 runnable 配置。
            research_context: 已取证研究子图提供的有界报告背景。
            final_report: 是否使用无工具的最终报告调用。

        Returns:
            Command: 携带状态更新与下一节点路由的 Command 对象。
        """
        # 取消或无匹配直接结束本次分析，不再让模型重新猜测代码。
        last = state.messages[-1] if state.messages else None
        if (
            isinstance(last, ToolMessage)
            and last.name in HOLDING_IMPORT_TOOL_NAMES
            and isinstance(last.content, str)
            and last.content.startswith("[TOOL_ERROR] ")
        ):
            failure_code, separator, notice = last.content.removeprefix("[TOOL_ERROR] ").partition(": ")
            if separator and failure_code in {
                "NOT_HOLDING_SCREENSHOT",
                "SCREENSHOT_UNREADABLE",
                "NO_HOLDING_ROWS",
                "IMPORT_PARSE_FAILED",
                "IMPORT_IMAGE_REQUIRED",
            }:
                return Command(update={"messages": [AIMessage(content=notice)]}, goto=END)
        outcome = state.fund_selection_result
        current_outcome = outcome if outcome is not None and outcome.turn_id == state.turn_id else None
        status = current_outcome.status if current_outcome is not None else None
        if status is None and (
            isinstance(last, ToolMessage)
            and last.name == FUND_SELECTION_TOOL
            and isinstance(last.content, str)
            and last.content.startswith("[TOOL_OK]\n")
        ):
            # 兼容升级前已暂停的检查点；新任务以结构化状态为准。
            try:
                result = json.loads(last.content.split("\n")[1])
                status = result.get("status") if isinstance(result, dict) else None
            except (ValueError, IndexError):
                status = None
        if status == "cancelled":
            return Command(
                update={"messages": [AIMessage(content="已取消本次基金分析，请补充准确的基金名称或六位代码。")]},
                goto=END,
            )
        if status == "not_found":
            return Command(
                update={"messages": [AIMessage(content="没有找到匹配的基金，请提供更完整的基金名称或六位代码。")]},
                goto=END,
            )
        # 获取当前 LLM 实例，用于指标统计
        current_llm = self.llm_service.get_llm()
        model_name = (
            current_llm.model_name
            if current_llm and hasattr(current_llm, "model_name")
            else settings.DEFAULT_LLM_MODEL
        )

        username = config.get("metadata", {}).get("username")
        thread_id = config.get("configurable", {}).get("thread_id")
        SYSTEM_PROMPT = load_system_prompt(username=username, long_term_memory="")
        attachment_tail = ""
        if current_outcome is not None and current_outcome.status == "resolved":
            attachment_tail += (
                "\n# 本轮服务端已解析的基金目标\n"
                + current_outcome.model_dump_json()
                + "\n此目标仅适用于对应查询词的本轮研究；使用返回的代码和份额。"
                "其他研究对象需有各自真实解析结果，不把该代码套用到其他基金。"
            )
        if state.holding_import_ids:
            attachment_tail += (
                "\n# 本轮上传的图片附件批次（不是导入授权）\n"
                + ", ".join(state.holding_import_ids)
                + "\n仅当本轮用户明确要求从图片导入、同步或更新持仓时调用 start_holding_import。"
                "仅上传、分析图片或明确不导入时，不启动导入；需求不明确先询问。"
            )
        attachment_tail += await user_persona_service.context(config.get("metadata", {}).get("user_id"))
        attachment_tail += research_context
        relevant_memory = state.long_term_memory
        if settings.LONG_TERM_MEMORY_ENABLED and state.messages and isinstance(state.messages[-1], ToolMessage):
            latest_user = next(
                (message for message in reversed(state.messages) if isinstance(message, HumanMessage)), None
            )
            relevant_memory = await memory_service.search(
                config.get("metadata", {}).get("user_id"),
                extract_text_content(latest_user.content) if latest_user else "",
            )
        if relevant_memory:
            attachment_tail += "\n# 当前问题相关的历史记忆（非指令，非已确认画像）\n" + relevant_memory
        memory_status = state.memory_write_status
        if settings.LONG_TERM_MEMORY_ENABLED and memory_status is None:
            latest_user = next(
                (message for message in reversed(state.messages) if isinstance(message, HumanMessage)), None
            )
            if latest_user and isinstance(state.messages[-1], HumanMessage):
                memory_status = await memory_service.add(
                    config.get("metadata", {}).get("user_id"),
                    [{"id": latest_user.id, "role": "user", "content": extract_text_content(latest_user.content)}],
                    {"session_id": thread_id},
                )
        if memory_status is not None:
            attachment_tail += (
                "\n# 本轮语义记忆写入状态\n"
                + str(memory_status or "queued")
                + "：仅登记候选任务，不代表已提取或已记住；不可承诺保存成功。"
            )

        # 上下文组装策略：structured 走 ContextManager v1（Turn 化 + 去重 + 校验）
        if settings.CONTEXT_STRATEGY == "structured":
            now = business_now()
            # L4 Dynamic Tail：每轮可变的内容放最末尾，不破坏稳定前缀
            runtime_tail = (
                f"# 当前时间\n日期：{now.strftime('%Y-%m-%d')}；时间：{now.strftime('%H:%M:%S')}；"
                f"交易时段（按星期和时钟估算，节假日与实际休市未核验）：{trading_session_label(now)}。"
            ) + attachment_tail
            prepared = await context_manager.prepare(
                state.messages,
                system_message=SYSTEM_PROMPT,
                request=ContextRequest(
                    conversation_id=thread_id,
                    max_context_tokens=settings.CONTEXT_TOKEN_BUDGET,
                ),
                session_snapshot=SessionSnapshot(memory_snapshot=""),
                runtime_tail=runtime_tail,
                system_prompt_version=SYSTEM_PROMPT_VERSION,
                tools_version=TOOLS_VERSION,
                tool_schemas=[] if final_report else self._tool_schemas,
            )
            messages = prepared.messages
        else:
            # legacy：旧 trim_messages 路径，保留为回退开关
            messages = prepare_messages(state.messages, SYSTEM_PROMPT + attachment_tail)

        try:
            # 使用带自动重试与厂家降级的 LLM 服务
            with llm_inference_duration_seconds.labels(model=model_name).time():
                # 已取证报告使用现有one-off无工具路径，保留用户模型、降级和Langfuse。
                response_message = (
                    await generate_research_report(messages, self.llm_service.call)
                    if final_report
                    else await self.llm_service.call(messages)
                )

            # 归一化响应，处理结构化内容块
            response_message = process_llm_response(response_message)
            if final_report and isinstance(response_message, AIMessage) and response_message.tool_calls:
                raise ValueError("research report unexpectedly requested tools")

            # KV Cache 指标：DeepSeek 等厂家会上报命中/未命中 token
            usage_metadata = getattr(response_message, "usage_metadata", None) or {}
            input_details = usage_metadata.get("input_token_details") or {}
            cache_hit = input_details.get("cache_read") or 0
            input_tokens = usage_metadata.get("input_tokens") or 0
            cache_miss = max(input_tokens - cache_hit, 0)
            hit_ratio = cache_hit / (cache_hit + cache_miss) if (cache_hit + cache_miss) else 0.0
            logger.info(
                "llm_cache_metrics",
                model=model_name,
                prompt_tokens=input_tokens,
                cache_hit_tokens=cache_hit,
                cache_miss_tokens=cache_miss,
                cache_hit_ratio=round(hit_ratio, 4),
            )
            llm_prompt_cache_hit_tokens.labels(model=model_name).inc(cache_hit)
            llm_prompt_cache_miss_tokens.labels(model=model_name).inc(cache_miss)
            llm_cache_hit_ratio.labels(model=model_name).set(hit_ratio)

            logger.info(
                "llm_response_generated",
                session_id=thread_id,
                model=model_name,
                environment=settings.ENVIRONMENT.value,
            )

            # 根据是否存在工具调用决定下一个节点
            if isinstance(response_message, AIMessage) and response_message.tool_calls:
                goto = (
                    "route_attachments"
                    if any(call["name"] == "start_holding_import" for call in response_message.tool_calls)
                    else "route_task"
                    if any(call["name"] == "start_research" for call in response_message.tool_calls)
                    else "fund_selection"
                    if any(call["name"] == FUND_SELECTION_TOOL for call in response_message.tool_calls)
                    else "holding_import"
                    if any(call["name"] in HOLDING_IMPORT_TOOL_NAMES for call in response_message.tool_calls)
                    else "tool_call"
                )
            else:
                goto = END

            return Command(update={"messages": [response_message], "memory_write_status": memory_status}, goto=goto)
        except Exception as e:
            logger.exception(
                "llm_call_failed_all_models",
                session_id=thread_id,
                error=str(e),
                environment=settings.ENVIRONMENT.value,
            )
            # 是否尝试过全部模型由 LLMService 判定，不能给超时/断流统一贴这个标签。
            raise Exception(f"failed to get llm response: {str(e)}") from e

    # 工具执行节点
    async def _tool_call(self, state: GraphState, config: RunnableConfig) -> Command:
        """执行最后一条消息里的工具调用.

        Args:
            state: 当前对话状态，包含消息与工具调用。
            config: 携带已认证身份的调用配置，会绑定进工具运行时，
                因此业务工具的 user_id 永远不来自 LLM。

        Returns:
            Command: 携带工具结果消息并路由回 chat 的 Command 对象。
        """
        tool_calls = state.messages[-1].tool_calls

        # 会中断的工具与同批其他调用一起跑会被重放：GraphInterrupt 丢弃本超步的全部
        # 写入，resume 时整个节点从头再执行，兄弟工具的副作用等于做了两次。
        # 这里直接拒掉混合批次——不执行任何调用，也就没有什么可重放；模型会在
        # 下一轮单独发起中断。
        if len(tool_calls) > 1 and any(call["name"] in _INTERRUPTING_TOOLS for call in tool_calls):
            logger.warning("tool_batch_with_interrupt_rejected", tool_count=len(tool_calls))
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=ToolResult.fail(
                                "INTERRUPT_BATCH_REJECTED",
                                "需要用户确认的调用必须单独发起；其余请求请在收到答复后重新提出。",
                                retryable=True,
                            ).to_text(),
                            name=call["name"],
                            tool_call_id=call["id"],
                        )
                        for call in tool_calls
                    ]
                },
                goto="chat",
            )

        # 业务工具从该运行时上下文读取调用者身份；并发执行会通过
        # 上下文变量继承它。身份缺失时优雅降级——由工具自己返回
        # PERMISSION_DENIED，而不是让节点把整个对话打崩。
        try:
            runtime = runtime_from_config(config)
            current_user = next(
                (message for message in reversed(state.messages) if isinstance(message, HumanMessage)), None
            )
            if current_user is not None:
                runtime = replace(
                    runtime,
                    user_message_id=str(current_user.id or ""),
                    user_message=extract_text_content(current_user.content),
                )
            set_tool_runtime(runtime)
        except ToolRuntimeError as e:
            set_tool_runtime(None)
            logger.warning("tool_runtime_context_missing", error=e.message)

        async def _execute_tool(tool_call: dict) -> ToolMessage:
            # Duplicate Tool Guard：执行前阻止当前 Run 内的同参数重复调用
            # （优先阻止而非事后删除历史 ToolMessage，保住配对与缓存）
            #
            # 计数窗口只限本轮：任何工具的数据都会随时间变化（净值、行情、识别
            # 状态、画像候选），跨用户轮累计会让一句正常的重复提问在长会话里被
            # 永久拦下。原先按工具名手写的白名单已经漏掉 get_fund_history、
            # get_calendar、search_funds、resolve_fund_for_analysis 等，去掉这份
            # 名单才是加新工具时不会腐烂的写法。
            tool_history = state.messages[:-1]
            for index in range(len(tool_history) - 1, -1, -1):
                if getattr(tool_history[index], "type", None) == "human":
                    tool_history = tool_history[index + 1 :]
                    break
            if self._tool_guard.should_block(
                count_signature_occurrences(tool_history, build_tool_signature(tool_call["name"], tool_call["args"]))
            ):
                logger.warning(
                    "tool_duplicate_blocked",
                    tool_name=tool_call["name"],
                    signature=build_tool_signature(tool_call["name"], tool_call["args"]),
                )
                return ToolMessage(
                    content=(
                        '[TOOL_ERROR] {"code": "DUPLICATE_TOOL_CALL", "message": '
                        '"该工具已经使用相同参数执行过，请使用已有结果继续任务。", "retryable": false}'
                    ),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            try:
                tool_result = await self.tools_by_name[tool_call["name"]].ainvoke(tool_call["args"])
            except GraphInterrupt:
                # interrupt() 依赖 GraphInterrupt 异常传递——必须原样
                # 抛给图，否则人工确认（HITL）的恢复流程会被破坏。
                raise
            except KeyError:
                # 模型幻觉出不存在的工具名；把错误作为 ToolMessage
                # 回传，让模型自行纠正，而不是让节点崩溃。
                logger.warning("unknown_tool_requested", tool_name=tool_call["name"])
                tool_result = f"Error: tool '{tool_call['name']}' does not exist."
            except Exception as e:
                logger.exception("tool_execution_failed", tool_name=tool_call["name"], error=str(e))
                tool_result = f"Error executing tool '{tool_call['name']}': {e}"
            return ToolMessage(
                content=tool_result,
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
            )

        # 多个工具调用时并发执行
        if len(tool_calls) == 1:
            outputs = [await _execute_tool(tool_calls[0])]
        else:
            outputs = list(await asyncio.gather(*[_execute_tool(tc) for tc in tool_calls]))

        return Command(update={"messages": outputs}, goto="chat")

    @staticmethod
    def _pending_interrupt(state: StateSnapshot) -> bool:
        """判断挂起任务是否是等待人工输入的中断.

        只有 HITL 中断才走 resume 恢复；工具循环崩溃（如触发递归上限）
        遗留的挂起节点不走 resume——那会让用户的新消息被当成 resume
        值吞掉，永远进不了对话线程。
        """
        return any(task.interrupts for task in state.tasks)

    @staticmethod
    def _pending_interrupt_value(state: StateSnapshot) -> object:
        """取等待人工输入的中断值；挂起但没有中断时回兜底文案.

        ``state.tasks`` 非空不代表 ``interrupts`` 非空：崩溃或断连遗留的挂起节点
        同样会让 ``state.next`` 有值，裸取 ``tasks[0].interrupts[0]`` 会 IndexError
        把一次可恢复状态变成 500。
        """
        for task in state.tasks or ():
            if task.interrupts:
                return task.interrupts[0].value
        return "Waiting for input."

    @staticmethod
    def _holding_review(state: StateSnapshot) -> AgentPendingAction | None:
        """提取图保存的复核卡和真实中断 ID，不信任客户端编造的卡片."""
        if not state.next:
            return None
        for task in state.tasks:
            for item in task.interrupts:
                if isinstance(item.value, str):
                    return HumanQuestionAction(interrupt_id=item.id, question=item.value)
                if isinstance(item.value, dict) and item.value.get("kind") in {
                    "holding_import_review",
                    "holding_import_processing",
                    "holding_import_account",
                    "fund_selection",
                }:
                    return _HOLDING_ACTION.validate_python({**item.value, "interrupt_id": item.id})
        return None

    @staticmethod
    def _interrupt_text(value: object) -> str:
        """结构化复核卡通过响应字段传输，正文只显示简短提示."""
        if isinstance(value, dict) and value.get("kind") == "human_question":
            return str(value["question"])
        if isinstance(value, dict) and value.get("kind") == "holding_import_review":
            return "图片识别已完成，请在人工复核面板检查识别结果并确认或取消；确认前不会更新持仓。"
        if isinstance(value, dict) and value.get("kind") in {
            "holding_import_processing",
            "holding_import_account",
            "fund_selection",
        }:
            return str(value.get("notice", "请继续截图导入流程。"))
        return str(value)

    async def get_pending_holding_review(self, session_id: str) -> AgentPendingAction | None:
        """客户端刷新后恢复持仓操作或基金选择卡片；保留旧方法名供已有客户端调用."""
        graph = await self._get_graph()
        state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        return self._holding_review(state)

    async def get_run_continuation(self, session_id: str) -> AgentRunContinuation | None:
        """人工决定已消费但后续节点失败时，返回原任务的继续入口，不伪造人工中断."""
        graph = await self._get_graph()
        state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        if not state.next or self._pending_interrupt(state) or not state.values.get("turn_id"):
            return None
        graph_state = GraphState.model_validate(state.values)
        outcome = graph_state.fund_selection_result
        selected = outcome.fund if outcome is not None and outcome.turn_id == state.values["turn_id"] else None
        task = graph_state.research_task
        if task is not None and task.turn_id == state.values["turn_id"]:
            if len(task.resolved_funds) == 1:
                selected = task.resolved_funds[0]
            elif len(task.resolved_funds) > 1:
                selected = None
        return AgentRunContinuation(
            turn_id=state.values["turn_id"],
            notice="原任务尚未完成，继续会保留已确认的对象和已取得的证据，无需重新选择。",
            selected_fund_code=selected.fund_code if selected else None,
            selected_fund_name=selected.fund_name if selected else None,
        )

    async def continue_run(
        self, session_id: str, turn_id: str, *, user_id: str, username: str | None = None
    ) -> list[Message]:
        """重试checkpoint中未完成节点，保留原轮次；不重新发送决定、启动工具或新消息."""
        graph = await self._get_graph()
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else [],
            "recursion_limit": settings.AGENT_RECURSION_LIMIT,
            "metadata": {"user_id": user_id, "session_id": session_id, "username": username},
        }
        state = await graph.aget_state(config)
        if state.values.get("turn_id") != turn_id or self._pending_interrupt(state):
            raise ValueError("agent_continuation_mismatch")
        if state.next:
            logger.info("agent_run_continued", session_id=session_id, turn_id=turn_id, next_nodes=state.next)
            await graph.ainvoke(None, config=config)
        state = await graph.aget_state(config)
        pending = self._holding_review(state)
        if pending:
            return [Message(role="assistant", content=self._interrupt_text(pending.model_dump()))]
        return self.__process_messages(state.values.get("messages", []))

    async def resume_holding_import(
        self, session_id: str, interrupt_id: str, decision: dict, *, user_id: str, username: str | None = None
    ) -> list[Message]:
        """由人工决策端点恢复指定中断，兼容持仓操作和基金选择."""
        graph = await self._get_graph()
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else [],
            "recursion_limit": settings.AGENT_RECURSION_LIMIT,
            "metadata": {"user_id": user_id, "session_id": session_id, "username": username},
        }
        # 连续复核可能让同一父任务暂停多次，不在每次 resume 中重复写
        # 非 reducer 通道。返回 chat 后，它会按最新工具结果重新检索记忆。
        await graph.ainvoke(Command(resume={interrupt_id: decision}), config=config)
        state = await graph.aget_state(config)
        pending = self._holding_review(state)
        if pending:
            return [Message(role="assistant", content=self._interrupt_text(pending.model_dump()))]
        return self.__process_messages(state.values.get("messages", []))

    def _build_graph(self, checkpointer) -> CompiledStateGraph:
        """在给定 checkpointer 之上组装 chat/tool_call/holding_import 图.

        从 ``create_graph`` 拆分而来，便于测试用内存 checkpointer
        编译出与生产完全一致的图拓扑。
        """
        graph_builder = StateGraph(GraphState)
        graph_builder.add_node("route_task", self._route_task, destinations=("chat", "continue_research"))
        graph_builder.add_node(
            "continue_research",
            continue_research,
            destinations=(
                "chat",
                "fund_selection",
                "fund_research",
                "fund_comparison",
                "portfolio_diagnosis",
                "allocation_analysis",
                "sector_research",
                "stock_research",
                "deep_fund_research",
                "deep_fund_comparison",
                "deep_portfolio_diagnosis",
                "deep_allocation_analysis",
                END,
            ),
        )
        graph_builder.add_node(
            "route_attachments", self._route_attachments, destinations=("holding_import", "chat", END)
        )
        graph_builder.add_node(
            "chat",
            self._chat,
            destinations=("tool_call", "route_attachments", "holding_import", "fund_selection", "route_task", END),
        )
        graph_builder.add_node("holding_import", build_holding_import_subgraph(self._tool_call))
        graph_builder.add_edge("holding_import", "chat")
        graph_builder.add_node("fund_selection", build_fund_selection_subgraph())
        graph_builder.add_edge("fund_selection", "continue_research")
        for intent in RESEARCH_INTENTS:
            graph_builder.add_node(
                intent,
                build_research_subgraph(intent, self._tool_call, self._research_report),
            )
            graph_builder.add_edge(intent, END)
            if intent not in DEEP_RESEARCH_INTENTS:
                continue
            # 多智能体是一条独立链路，节点名与 continue_research 的 _chain_node 对应。
            graph_builder.add_node(
                "deep_" + intent,
                build_deep_research_subgraph(
                    intent, self._tool_call, self._research_report, self._research_agent_call
                ),
            )
            graph_builder.add_edge("deep_" + intent, END)
        graph_builder.add_node(
            "tool_call",
            self._tool_call,
            destinations=("chat",),
            retry_policy=RetryPolicy(max_attempts=3),
        )
        graph_builder.set_entry_point("route_task")
        graph_builder.set_finish_point("chat")

        return graph_builder.compile(
            checkpointer=checkpointer,
            # PROJECT_NAME 本身可能已含 "Agent"（本机 .env 就是 "Fund Agent"），
            # 再拼一遍就成了 trace 面板上的 "Fund Agent Agent"。产品名与环境即可定位。
            name=f"{settings.PROJECT_NAME} ({settings.ENVIRONMENT.value})",
        )

    async def _route_task(self, state: GraphState, config: RunnableConfig) -> Command:
        """新消息先登记记忆，路由不额外调用分类模型；resume不重新进入入口."""
        status = state.memory_write_status
        last = state.messages[-1] if state.messages else None
        if isinstance(last, HumanMessage) and status is None and settings.LONG_TERM_MEMORY_ENABLED:
            status = await memory_service.add(
                config.get("metadata", {}).get("user_id"),
                [{"id": last.id, "role": "user", "content": extract_text_content(last.content)}],
                {"session_id": config.get("configurable", {}).get("thread_id")},
            )
            status = status or "queued"
        command = route_task(state)
        # 服务端授权的快路径不带 update，此时任务本来就在 state 里；
        # 只看 command.update 会让日志一直报 intent=None（我前两轮就被它误导过）。
        task = (command.update or {}).get("research_task") or state.research_task
        logger.info(
            "agent_task_routed",
            turn_id=state.turn_id,
            destination=command.goto,
            intent=task.request.intent if task is not None else None,
        )
        return Command(update={**(command.update or {}), "memory_write_status": status}, goto=command.goto)

    async def _research_agent_call(
        self,
        prompt: str,
        data: str,
        schema: type[BaseModel],
        config: RunnableConfig,
        on_text: Callable[[str], None] | None = None,
    ) -> BaseModel:
        """Structured one-off calls inherit graph callbacks and never mutate shared tool bindings."""
        if config.get("metadata", {}).get("langgraph_node") in {"portfolio_analysis", "portfolio_revision"}:
            persona = await user_persona_service.context(config.get("metadata", {}).get("user_id"))
            if persona:
                payload = json.loads(data)
                payload["confirmed_user_profile"] = persona
                data = json.dumps(payload, ensure_ascii=False)
        current_llm = self.llm_service.get_llm()
        model_name = str(getattr(current_llm, "model_name", settings.DEFAULT_LLM_MODEL) or "")
        # 只有 GLM-5.3 系列认 reasoning_effort；其他厂商传了就当没传，别把请求弄失败。
        effort: dict[str, Any] = (
            {"extra_body": {"reasoning_effort": settings.MULTI_ROLE_RESEARCH_REASONING_EFFORT}}
            if model_name.lower().startswith("glm-5.3")
            else {}
        )
        messages: list[Any] = [SystemMessage(content=prompt), HumanMessage(content=data)]
        node = str(config.get("metadata", {}).get("langgraph_node") or "")
        for attempt in range(_RESEARCH_CONTRACT_ATTEMPTS):
            try:
                with llm_inference_duration_seconds.labels(model=model_name).time():
                    result = await self.llm_service.call(
                        messages,
                        response_format=schema,
                        on_text=on_text,
                        max_tokens=settings.MULTI_ROLE_RESEARCH_MAX_TOKENS,
                        **effort,
                    )
                return schema.model_validate(result)
            except LLMContractViolation as error:
                if attempt + 1 >= _RESEARCH_CONTRACT_ATTEMPTS:
                    # 回喂一次仍不合：报成契约违约，节点会记 failed。日志与"连接中断"
                    # 分开，界面上才分得清"模型没做"和"做了但字段不合"。
                    logger.warning(
                        "research_contract_violation",
                        node=node,
                        model=error.model_name,
                        schema=schema.__name__,
                        field_errors=error.field_errors[:400],
                    )
                    raise
                logger.info("research_contract_repaired", node=node, schema=schema.__name__, attempt=attempt + 1)
                messages = [
                    *messages,
                    HumanMessage(
                        content=(
                            "上一次输出不符合结构契约，字段错误如下，请只修正这些字段后重新输出完整结果，"
                            "不要改动其他内容：\n" + error.field_errors[:600]
                        )
                    ),
                ]
        raise RuntimeError("研究调用未产生结果")

    async def _research_report(self, state: ResearchGraphState, config: RunnableConfig, context: str) -> AIMessage:
        """子图只回传最终回答和紧凑结果，父图不再次改写或重复执行工具."""
        command = await self._chat(
            GraphState(
                messages=[message for message in state.messages if isinstance(message, HumanMessage)][-1:],
                turn_id=state.turn_id,
                long_term_memory=state.long_term_memory,
                research_task=state.research_task,
                memory_write_status=state.memory_write_status,
            ),
            config,
            research_context=context,
            final_report=True,
        )
        message = (command.update or {})["messages"][0]
        if not isinstance(message, AIMessage):
            raise ValueError("research report requires assistant message")
        return message

    async def _route_attachments(self, state: GraphState, config: RunnableConfig) -> Command:
        """主图先按用户需求提出导入，再校验本轮附件；单有图片不会进入子图."""
        last = state.messages[-1] if state.messages else None
        if not isinstance(last, AIMessage) or not any(
            call["name"] == "start_holding_import" for call in last.tool_calls
        ):
            return Command(goto="chat")
        if not state.holding_import_ids:
            notice = "请先上传基金持仓截图，图片需清晰显示基金名称及持有金额或份额，再告诉我要导入到哪个账户。持仓尚未更新。"
            return Command(
                update={
                    "messages": [
                        *[
                            ToolMessage(
                                content=ToolResult.fail("IMPORT_IMAGE_REQUIRED", notice).to_text(),
                                name=call["name"],
                                tool_call_id=call["id"],
                            )
                            for call in last.tool_calls
                        ],
                        AIMessage(content=notice),
                    ]
                },
                goto=END,
            )
        try:
            runtime = runtime_from_config(config)
            for import_id in state.holding_import_ids:
                await agent_holding_import_service.detail(runtime.user_id, runtime.thread_id, import_id)
        except Exception:
            logger.exception("holding_import_route_validation_failed")
            notice = "无法读取本轮上传的截图批次，请稍后重试或重新上传；持仓未更新。"
            return Command(
                update={
                    "messages": [
                        *[
                            ToolMessage(
                                content=ToolResult.fail("IMPORT_UNAVAILABLE", notice, retryable=True).to_text(),
                                name=call["name"],
                                tool_call_id=call["id"],
                            )
                            for call in last.tool_calls
                        ],
                        AIMessage(content=notice),
                    ]
                },
                goto=END,
            )
        results = [
            ToolMessage(
                content=(
                    ToolResult.ok({"status": "routing", "import_ids": state.holding_import_ids}).to_text()
                    if call["name"] == "start_holding_import"
                    else ToolResult.fail(
                        "HOLDING_IMPORT_PENDING", "先处理本轮持仓导入，完成后如有需要再查询其他数据。"
                    ).to_text()
                ),
                name=call["name"],
                tool_call_id=call["id"],
            )
            for call in last.tool_calls
        ]
        calls = [
            {
                "name": "request_holding_import_confirmation",
                "args": {"import_id": import_id},
                "id": uuid4().hex,
                "type": "tool_call",
            }
            for import_id in state.holding_import_ids
        ]
        logger.info("holding_import_intent_routed", session_id=runtime.thread_id, image_batches=len(calls))
        return Command(update={"messages": [*results, AIMessage(content="", tool_calls=calls)]}, goto="holding_import")

    async def resolve_holding_account_reply(
        self, pending: AgentPendingAction, text: str, user_id: str | None
    ) -> dict | None:
        """普通聊天可补充目标账户，但不能确认正式持仓写入."""
        if not isinstance(pending, HoldingImportAccountSelection) or user_id is None:
            return None
        content = text.strip()
        exact = [account.id for account in pending.accounts if content in {account.name, str(account.id)}]
        account_id = (
            exact[0] if len(exact) == 1 else await agent_holding_import_service.resolve_account(int(user_id), content)
        )
        if account_id is None:
            return None
        return {"import_id": pending.import_id, "account_id": account_id}

    async def create_graph(self) -> CompiledStateGraph:
        """创建并配置 LangGraph 工作流.

        Returns:
            CompiledStateGraph: 已配置的图实例，一定带 checkpointer。

        Raises:
            Exception: 任何环境下构建失败都会抛出。
        """
        if self._graph is None:
            try:
                # 创建失败会直接抛出——没有 checkpointer 就没有服务。
                connection_pool = await self._get_connection_pool()
                checkpointer = AsyncPostgresSaver(connection_pool)
                await checkpointer.setup()

                self._graph = self._build_graph(checkpointer)

                logger.info(
                    "graph_created",
                    graph_name=f"{settings.PROJECT_NAME} ({settings.ENVIRONMENT.value})",
                    environment=settings.ENVIRONMENT.value,
                    has_checkpointer=checkpointer is not None,
                )
            except Exception as e:
                logger.exception("graph_creation_failed", error=str(e), environment=settings.ENVIRONMENT.value)
                raise e

        return self._graph

    async def _get_graph(self) -> CompiledStateGraph:
        """返回已编译的图，首次访问时按需创建.

        Raises:
            Exception: ``create_graph()`` 初始化失败时向上抛出。
                调用方可以认为返回值不会是 ``None``。
        """
        if self._graph is None:
            self._graph = await self.create_graph()
        return self._graph

    @staticmethod
    def _new_turn_state(
        messages: list[Message],
        memory: str,
        holding_import_ids: list[str] | None,
        holding_account_id: int | None,
    ) -> dict[str, Any]:
        """流式/非流式同一入口；只在新提问时清理本轮目标，恢复保持不变."""
        return {
            "messages": dump_messages(messages),
            "long_term_memory": memory,
            "turn_id": uuid4().hex,
            "fund_selection_result": None,
            "holding_import_ids": holding_import_ids or [],
            "holding_account_id": holding_account_id,
            "holding_instruction": messages[-1].content,
            "research_task": None,
            "research_result": None,
            "memory_write_status": None,
        }

    @staticmethod
    def _client_research_task(
        turn_id: str,
        instruction: str,
        codes: list[str],
        strategy: Literal["single", "multi_role"],
    ) -> ResearchTask:
        """基金页按钮的直接授权：不经过模型提出 start_research，对象仍是待解析代码.

        与追问按钮共用 ``route_task`` 的同一道服务端放行口；名称解析、歧义时的人工
        选卡和有界取证一律沿用原节点，不另开一条链。
        """
        return ResearchTask(
            turn_id=turn_id,
            request=client_research_request(codes, strategy),
            instruction=instruction,
            requested_by="client",
        )

    async def _memory_snapshot(self, *, user_id: str | None, thread_id: str, query: str) -> str:
        """每次按当前问题召回；数据库版本缓存代替冻结的会话快照."""
        if not settings.LONG_TERM_MEMORY_ENABLED or user_id is None:
            return ""
        return await memory_service.search(user_id, query)

    async def get_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        holding_import_ids: list[str] | None = None,
        holding_account_id: int | None = None,
        research_followup_id: str | None = None,
        research_fund_codes: list[str] | None = None,
        research_strategy: Literal["single", "multi_role"] = "single",
    ) -> list[Message]:
        """从 LLM 获取响应.

        Args:
            messages (list[Message]): 发送给 LLM 的消息列表。
            session_id (str): 会话 ID。
            user_id (Optional[str]): 用户 ID。
            username (Optional[str]): 用户显示名。
            holding_import_ids: 本轮已经验证归属的图片导入批次。
            holding_account_id: 用户显式指定的目标账户，不做默认选择。
            research_followup_id: 绑定本会话已有报告的进一步研究标识。
            research_fund_codes: 选基金面板直接授权的研究对象（六位代码）。
            research_strategy: 成本档位，multi_role 才会拉起三角色合议。

        Returns:
            list[Message]: LLM 的响应消息。
        """
        graph = await self._get_graph()
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            # 每轮工具调用消耗一个 chat 步 + 一个 tool 步；25 把循环
            # 上限控制在约 12 轮，防止工具密集的计划无限跑下去。
            "recursion_limit": settings.AGENT_RECURSION_LIMIT,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
                # Langfuse 3.x 只从这几个 metadata 键读 trace 级属性；没有它们，
                # evals 就分不出单档与深度档，两种模式没法同题对照。
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "langfuse_tags": [f"strategy:{research_strategy}"],
            },
        }

        try:
            state = await graph.aget_state(config)
            followup = validate_research_followup(state, research_followup_id) if research_followup_id else None
            cached = completed_followup(state, research_followup_id) if research_followup_id else None
            if cached is not None:
                return self.__process_messages(state.values["messages"])
            pending = self._holding_review(state)
            if pending and not isinstance(pending, HumanQuestionAction):
                return [Message(role="assistant", content=self._interrupt_text(pending.model_dump()))]
            # 每轮按当前问题检索，记忆放动态尾部保持稳定系统前缀。
            relevant_memory = (
                ""
                if holding_import_ids
                else await self._memory_snapshot(
                    user_id=user_id,
                    thread_id=session_id,
                    query=followup.instruction if followup is not None else messages[-1].content,
                )
            )

            if state.next and self._pending_interrupt(state):
                logger.info("resuming_interrupted_graph", session_id=session_id, next_nodes=state.next)
                response = await graph.ainvoke(
                    Command(resume=messages[-1].content, update={"long_term_memory": relevant_memory}),
                    config=config,
                )
            else:
                # 没有等待人工输入的中断：作为全新提问处理。崩溃遗留的挂起
                # 节点（比如触发递归上限的那次）会被这次新运行自然覆盖，
                # 用户的新消息会真正进入对话线程。
                new_input = self._new_turn_state(messages, relevant_memory, holding_import_ids, holding_account_id)
                if followup is not None:
                    new_input["research_task"] = followup.model_copy(update={"turn_id": new_input["turn_id"]})
                elif research_fund_codes:
                    new_input["research_task"] = self._client_research_task(
                        new_input["turn_id"], messages[-1].content, research_fund_codes, research_strategy
                    )
                response = await graph.ainvoke(
                    input=new_input,
                    config=config,
                )

            # 检查本次调用期间图是否被中断
            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = self._pending_interrupt_value(state)
                logger.info(
                    "graph_interrupted", session_id=session_id, interrupt_value=self._interrupt_text(interrupt_value)
                )
                return [Message(role="assistant", content=self._interrupt_text(interrupt_value))]

            return self.__process_messages(response["messages"])
        except GraphRecursionError:
            # 工具循环打满上限：把原始报错变成用户能理解的提示，而不是 500
            logger.warning("graph_recursion_limit_hit", session_id=session_id)
            return [
                Message(
                    role="assistant",
                    content="抱歉，这个问题需要的处理步骤过多，已中途停止。建议把问题拆得更具体一些再试，例如先问某一只基金的情况。",
                )
            ]
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = self._pending_interrupt_value(state)
            logger.info(
                "graph_interrupted", session_id=session_id, interrupt_value=self._interrupt_text(interrupt_value)
            )
            return [Message(role="assistant", content=self._interrupt_text(interrupt_value))]
        except Exception as e:
            logger.exception("get_response_failed", error=str(e), session_id=session_id)
            raise

    async def get_stream_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        holding_import_ids: list[str] | None = None,
        holding_account_id: int | None = None,
        research_followup_id: str | None = None,
        research_fund_codes: list[str] | None = None,
        research_strategy: Literal["single", "multi_role"] = "single",
        resume: FundSelectionDecision | AgentContinueRequest | None = None,
    ) -> AsyncGenerator[str | ResearchProgress | ResearchActivity, None]:
        """以流式方式从 LLM 获取响应.

        Args:
            messages (list[Message]): 发送给 LLM 的消息列表。
            session_id (str): 会话 ID。
            user_id (Optional[str]): 用户 ID。
            username (Optional[str]): 用户显示名。
            holding_import_ids: 本轮已经验证归属的图片导入批次。
            holding_account_id: 用户显式指定的目标账户。
            research_followup_id: 绑定本会话已有报告的进一步研究标识。
            research_fund_codes: 选基金面板直接授权的研究对象（六位代码）。
            research_strategy: 成本档位，multi_role 才会拉起三角色合议。
            resume: 已验证的人工决定或原任务轮次，不创建新的用户消息。

        Yields:
            str: LLM 响应的文本片段。
        """
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            # 与非流式路径相同的工具循环上限。
            "recursion_limit": settings.AGENT_RECURSION_LIMIT,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
                # Langfuse 3.x 只从这几个 metadata 键读 trace 级属性；没有它们，
                # evals 就分不出单档与深度档，两种模式没法同题对照。
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "langfuse_tags": [f"strategy:{research_strategy}"],
            },
        }
        graph = await self._get_graph()

        try:
            state = await graph.aget_state(config)
            # 本轮开始前已经入库的消息 id。stream_mode="messages" 不只转发模型 token，
            # 还会把节点输出里的消息全部转发；挂载成父节点的子图，其输出就是包含整段
            # 历史的完整状态，于是上一轮报告会被当成本轮新产出重新发射。见下方过滤。
            prior_message_ids = {
                message.id for message in state.values.get("messages", []) if getattr(message, "id", None)
            }
            if resume is not None:
                graph_input = self._resume_input(state, resume)
                if graph_input is None and not state.next:
                    saved = self.__process_messages(state.values.get("messages", []))
                    if saved and saved[-1].role == "assistant":
                        yield saved[-1].content
                    return
            else:
                followup = validate_research_followup(state, research_followup_id) if research_followup_id else None
                cached = completed_followup(state, research_followup_id) if research_followup_id else None
                if cached is not None:
                    yield extract_text_content(cached.content)
                    return
                pending = self._holding_review(state)
                if pending and not isinstance(pending, HumanQuestionAction):
                    yield self._interrupt_text(pending.model_dump())
                    return
                relevant_memory = (
                    ""
                    if holding_import_ids
                    else await self._memory_snapshot(
                        user_id=user_id,
                        thread_id=session_id,
                        query=followup.instruction if followup is not None else messages[-1].content,
                    )
                )

                if state.next and self._pending_interrupt(state):
                    logger.info("resuming_interrupted_graph_stream", session_id=session_id, next_nodes=state.next)
                    graph_input = Command(resume=messages[-1].content, update={"long_term_memory": relevant_memory})
                else:
                    graph_input = self._new_turn_state(
                        messages, relevant_memory, holding_import_ids, holding_account_id
                    )
                    if followup is not None:
                        graph_input["research_task"] = followup.model_copy(update={"turn_id": graph_input["turn_id"]})
                    elif research_fund_codes:
                        graph_input["research_task"] = self._client_research_task(
                            graph_input["turn_id"], messages[-1].content, research_fund_codes, research_strategy
                        )

            stream_started = time.perf_counter()
            first_token_at: float | None = None
            research_buffer = ""
            research_emitted = ""
            # 两条链的节点名都要认：漏了 deep_ 前缀，父图转发的子图消息就不再被抑制，
            # 报告正文会在流里出现两遍。
            research_nodes = {
                "write_report",
                *RESEARCH_INTENTS,
                *("deep_" + intent for intent in DEEP_RESEARCH_INTENTS),
            }
            async with aclosing(
                cast(
                    AsyncGenerator[Any, None],
                    graph.astream(
                        graph_input,
                        config,
                        stream_mode=["messages", "custom"],
                        subgraphs=True,
                    ),
                )
            ) as events:
                async for _namespace, mode, event in events:
                    if mode == "custom":
                        if isinstance(event, dict) and event.get("kind") == "research_progress":
                            yield ResearchProgress.model_validate(event)
                        elif isinstance(event, dict) and event.get("kind") == "research_activity":
                            yield ResearchActivity.model_validate(event)
                        continue
                    token, metadata = event
                    if isinstance(metadata, dict) and metadata.get("research_internal"):
                        continue
                    if (
                        not _namespace
                        and isinstance(metadata, dict)
                        and metadata.get("langgraph_node") in research_nodes - {"write_report"}
                    ):
                        # The parent re-emits a child's saved message; only its original stream is public.
                        continue
                    if not isinstance(token, (AIMessage, AIMessageChunk)):
                        continue
                    if getattr(token, "id", None) in prior_message_ids:
                        # 已入库的消息不是本轮新产出，不能当作正文发给客户端。
                        continue

                    text = extract_text_content(token.content)
                    if text and isinstance(metadata, dict) and metadata.get("langgraph_node") in research_nodes:
                        # 文字照常流式；新图表引用及其后缀等最终服务端校验后再发。
                        # 留一段尾部处理跨token分割的代码栅栏，禁止未校验引用触发取数。
                        research_buffer += text
                        marker = research_buffer.find("```research-chart")
                        boundary = marker if marker >= 0 else max(0, len(research_buffer) - 32)
                        text = research_buffer[len(research_emitted) : boundary]
                        research_emitted += text
                    if text:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                            logger.info(
                                "llm_ttft",
                                ttft_ms=round((first_token_at - stream_started) * 1000, 1),
                                session_id=session_id,
                            )
                        yield text

            # 流结束后检查中断；记忆在 chat 节点已登记。
            state = await graph.aget_state(config)
            if research_buffer and state.values.get("research_result") is not None:
                answer = next(
                    (
                        message
                        for message in reversed(state.values.get("messages", []))
                        if isinstance(message, AIMessage)
                    ),
                    None,
                )
                final_text = extract_text_content(answer.content) if answer is not None else ""
                if not final_text.startswith(research_emitted):
                    raise ValueError("validated research response differs from streamed prefix")
                if len(final_text) > len(research_emitted):
                    yield final_text[len(research_emitted) :]
            if state.next:
                interrupt_value = self._pending_interrupt_value(state)
                logger.info(
                    "graph_interrupted_stream",
                    session_id=session_id,
                    interrupt_value=self._interrupt_text(interrupt_value),
                )
                yield self._interrupt_text(interrupt_value)
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = self._pending_interrupt_value(state)
            logger.info(
                "graph_interrupted_stream",
                session_id=session_id,
                interrupt_value=self._interrupt_text(interrupt_value),
            )
            yield self._interrupt_text(interrupt_value)
        except GraphRecursionError:
            # 工具循环打满上限：向流式客户端推送一句可理解的提示，而不是 500
            logger.warning("graph_recursion_limit_hit_stream", session_id=session_id)
            yield "抱歉，这个问题需要的处理步骤过多，已中途停止。建议把问题拆得更具体一些再试，例如先问某一只基金的情况。"
        except Exception as stream_error:
            logger.exception("stream_processing_failed", error=str(stream_error), session_id=session_id)
            raise stream_error

    @staticmethod
    def _resume_input(state: StateSnapshot, payload: FundSelectionDecision | AgentContinueRequest) -> Command | None:
        """选择只消费当前中断；继续只重跑原轮次未完成的节点."""
        if isinstance(payload, FundSelectionDecision):
            pending = LangGraphAgent._holding_review(state)
            if not isinstance(pending, FundSelectionAction) or pending.interrupt_id != payload.interrupt_id:
                raise ValueError("fund_selection_interrupt_mismatch")
            if payload.decision == "select" and payload.fund_code not in {
                item.fund_code for item in pending.candidates
            }:
                raise ValueError("fund_not_in_candidates")
            return Command(resume={payload.interrupt_id: payload.model_dump()})
        if state.values.get("turn_id") != payload.turn_id or LangGraphAgent._pending_interrupt(state):
            raise ValueError("agent_continuation_mismatch")
        return None

    async def validate_stream_resume(
        self, session_id: str, payload: FundSelectionDecision | AgentContinueRequest
    ) -> None:
        """发送流式响应头之前，在会话锁内核验中断和轮次."""
        graph = await self._get_graph()
        state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        self._resume_input(state, payload)

    async def get_chat_history(self, session_id: str) -> list[Message]:
        """获取指定会话的聊天历史.

        Args:
            session_id (str): 会话 ID。

        Returns:
            list[Message]: 聊天历史消息。
        """
        graph = await self._get_graph()

        config: RunnableConfig = {"configurable": {"thread_id": session_id}}
        state: StateSnapshot = await graph.aget_state(config=config)
        return self.__process_messages(state.values["messages"]) if state.values else []

    async def validate_research_source(self, session_id: str, reference: str) -> None:
        """Validate references before streaming and again under the session lock."""
        graph = await self._get_graph()
        state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        validate_research_followup(state, reference)

    def __process_messages(self, messages: list[BaseMessage]) -> list[Message]:
        result: list[Message] = []
        completed_sources = {
            message.additional_kwargs.get("research_followup_source")
            for message in messages
            if isinstance(message, AIMessage)
        }
        for original in messages:
            source = research_source(original)
            outcomes = original.additional_kwargs.get("research_roles") if isinstance(original, AIMessage) else None
            review_status = (
                original.additional_kwargs.get("research_review_status") if isinstance(original, AIMessage) else None
            )
            for message in convert_to_openai_messages([original]):
                if message["role"] in ["assistant", "user"] and message["content"]:
                    result.append(
                        Message(
                            role=message["role"],
                            content=str(message["content"]),
                            research_id=source.turn_id if source and source.turn_id not in completed_sources else None,
                            research_intent=source.request.intent
                            if source and source.turn_id not in completed_sources
                            else None,
                            research_roles=outcomes,
                            research_review_status=review_status,
                        )
                    )
        return result

    async def clear_chat_history(self, session_id: str) -> None:
        """清空指定会话的全部聊天历史.

        Args:
            session_id: 要清空的会话 ID。

        Raises:
            Exception: 清空过程出错时抛出。
        """
        try:
            # 确保连接池已在当前事件循环中初始化
            conn_pool = await self._get_connection_pool()
            if conn_pool is None:
                raise RuntimeError("connection pool unavailable; cannot clear chat history")

            # 用 pipeline 把所有 DELETE 合并到一次往返
            async with conn_pool.connection() as conn:
                async with conn.transaction():
                    async with conn.pipeline():
                        for table in settings.CHECKPOINT_TABLES:
                            await conn.execute(
                                sql.SQL("DELETE FROM {} WHERE thread_id = %s").format(sql.Identifier(table)),
                                (session_id,),
                            )
                        await conn.execute(
                            'UPDATE "session" SET context_state = NULL, context_state_legacy = NULL, '
                            "context_revision = context_revision + 1 WHERE id = %s",
                            (session_id,),
                        )
                context_manager.forget_thread(session_id)
                self._memory_snapshots.pop(session_id, None)
                logger.info(
                    "checkpoint_tables_cleared_for_session",
                    tables=settings.CHECKPOINT_TABLES,
                    session_id=session_id,
                )

        except Exception as e:
            logger.exception(
                "clear_chat_history_operation_failed",
                session_id=session_id,
                error=str(e),
            )
            raise
