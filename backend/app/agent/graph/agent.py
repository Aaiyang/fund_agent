"""Agent 图与 LLM 交互的实现：chat / tool_call 节点、检查点与会话管理."""

import asyncio
import time
from typing import (
    AsyncGenerator,
    Optional,
    cast,
)
from urllib.parse import quote_plus

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
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

from app.core.config import settings
from app.agent.tools import tools
from app.agent.tools.guard import DuplicateToolGuard, build_tool_signature, count_signature_occurrences
from app.agent.tools.runtime import ToolRuntimeError, runtime_from_config, set_tool_runtime
from app.core.logging import logger
from app.core.metrics import llm_inference_duration_seconds
from app.core.observability import langfuse_callback_handler
from app.agent.prompts import load_system_prompt
from app.schemas import (
    GraphState,
    Message,
)
from app.utils.clock import business_now, trading_session_label
from app.agent.prompts import SYSTEM_PROMPT_VERSION
from app.agent.tools.registry import TOOLS_VERSION
from app.core.metrics import (
    llm_cache_hit_ratio,
    llm_prompt_cache_hit_tokens,
    llm_prompt_cache_miss_tokens,
)
from app.services.llm import llm_service
from app.services.memory import memory_service
from app.agent.context import (
    context_manager,
    dump_messages,
    extract_text_content,
    prepare_messages,
    process_llm_response,
)
from app.agent.context.models import ContextRequest, SessionSnapshot

PostgresConnPool = AsyncConnectionPool[AsyncConnection[DictRow]]

# 保存后台任务引用，防止事件循环把尚未执行完的任务垃圾回收
# （与 session_naming 中相同的模式）。
_background_tasks: set[asyncio.Task] = set()

# 图级“超级步数”上限（chat/tool 之间的跳转）。一轮工具调用消耗两步，
# 因此本限制把每轮对话的工具调用次数约束在约 12 次以内。
TOOL_LOOP_RECURSION_LIMIT = 25


def _spawn_background(coro) -> None:
    """把协程放入后台执行，不等待其完成."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
        # 会话级记忆快照（L1）：会话内冻结，保证系统提示词前缀稳定
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

    async def _chat(self, state: GraphState, config: RunnableConfig) -> Command:
        """处理对话状态并生成模型响应.

        Args:
            state (GraphState): 当前对话状态。
            config (RunnableConfig): 本次调用的 runnable 配置。

        Returns:
            Command: 携带状态更新与下一节点路由的 Command 对象。
        """
        # 获取当前 LLM 实例，用于指标统计
        current_llm = self.llm_service.get_llm()
        model_name = (
            current_llm.model_name
            if current_llm and hasattr(current_llm, "model_name")
            else settings.DEFAULT_LLM_MODEL
        )

        username = config.get("metadata", {}).get("username")
        thread_id = config.get("configurable", {}).get("thread_id")
        SYSTEM_PROMPT = load_system_prompt(username=username, long_term_memory=state.long_term_memory)

        # 上下文组装策略：structured 走 ContextManager v1（Turn 化 + 去重 + 校验）
        if settings.CONTEXT_STRATEGY == "structured":
            now = business_now()
            # L4 Dynamic Tail：每轮可变的内容放最末尾，不破坏稳定前缀
            runtime_tail = (
                f"# 当前时间\n日期：{now.strftime('%Y-%m-%d')}；时间：{now.strftime('%H:%M:%S')}；"
                f"交易时段：{trading_session_label(now)}。"
            )
            prepared = await context_manager.prepare(
                state.messages,
                system_message=SYSTEM_PROMPT,
                request=ContextRequest(
                    conversation_id=thread_id,
                    max_context_tokens=settings.CONTEXT_TOKEN_BUDGET,
                ),
                session_snapshot=SessionSnapshot(memory_snapshot=state.long_term_memory),
                runtime_tail=runtime_tail,
                system_prompt_version=SYSTEM_PROMPT_VERSION,
                tools_version=TOOLS_VERSION,
                tool_schemas=self._tool_schemas,
            )
            messages = prepared.messages
        else:
            # legacy：旧 trim_messages 路径，保留为回退开关
            messages = prepare_messages(state.messages, SYSTEM_PROMPT)

        try:
            # 使用带自动重试与厂家降级的 LLM 服务
            with llm_inference_duration_seconds.labels(model=model_name).time():
                response_message = await self.llm_service.call(messages)

            # 归一化响应，处理结构化内容块
            response_message = process_llm_response(response_message)

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
                goto = "tool_call"
            else:
                goto = END

            return Command(update={"messages": [response_message]}, goto=goto)
        except Exception as e:
            logger.exception(
                "llm_call_failed_all_models",
                session_id=thread_id,
                error=str(e),
                environment=settings.ENVIRONMENT.value,
            )
            raise Exception(f"failed to get llm response after trying all models: {str(e)}")

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

        # 业务工具从该运行时上下文读取调用者身份；并发执行会通过
        # 上下文变量继承它。身份缺失时优雅降级——由工具自己返回
        # PERMISSION_DENIED，而不是让节点把整个对话打崩。
        try:
            set_tool_runtime(runtime_from_config(config))
        except ToolRuntimeError as e:
            logger.warning("tool_runtime_context_missing", error=e.message)

        async def _execute_tool(tool_call: dict) -> ToolMessage:
            # Duplicate Tool Guard：执行前阻止当前 Run 内的同参数重复调用
            # （优先阻止而非事后删除历史 ToolMessage，保住配对与缓存）
            if self._tool_guard.should_block(
                count_signature_occurrences(
                    state.messages[:-1], build_tool_signature(tool_call["name"], tool_call["args"])
                )
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
        return bool(state.tasks and state.tasks[0].interrupts)

    def _build_graph(self, checkpointer) -> CompiledStateGraph:
        """在给定 checkpointer 之上组装 chat/tool_call 图.

        从 ``create_graph`` 拆分而来，便于测试用内存 checkpointer
        编译出与生产完全一致的图拓扑。
        """
        graph_builder = StateGraph(GraphState)
        graph_builder.add_node("chat", self._chat, destinations=("tool_call", END))
        graph_builder.add_node(
            "tool_call",
            self._tool_call,
            destinations=("chat",),
            retry_policy=RetryPolicy(max_attempts=3),
        )
        graph_builder.set_entry_point("chat")
        graph_builder.set_finish_point("chat")

        return graph_builder.compile(
            checkpointer=checkpointer,
            name=f"{settings.PROJECT_NAME} Agent ({settings.ENVIRONMENT.value})",
        )

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
                    graph_name=f"{settings.PROJECT_NAME} Agent",
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

    async def _memory_snapshot(self, *, user_id: str | None, thread_id: str, query: str) -> str:
        """会话级记忆快照（L1 Session Snapshot）.

        会话首次调用时检索 mem0 并冻结，当前会话内不再刷新——后台写入
        可以继续，但注入用快照，保证系统提示词前缀逐字节稳定（KV Cache）。
        """
        if not settings.LONG_TERM_MEMORY_ENABLED or user_id is None:
            return "No relevant memory found."
        snapshot = self._memory_snapshots.get(thread_id)
        if snapshot is None:
            snapshot = await memory_service.search(user_id, query)
            snapshot = snapshot or "No relevant memory found."
            self._memory_snapshots[thread_id] = snapshot
            logger.info("memory_snapshot_created", thread_id=thread_id)
        return snapshot

    async def get_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> list[Message]:
        """从 LLM 获取响应.

        Args:
            messages (list[Message]): 发送给 LLM 的消息列表。
            session_id (str): 会话 ID。
            user_id (Optional[str]): 用户 ID。
            username (Optional[str]): 用户显示名。

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
            "recursion_limit": TOOL_LOOP_RECURSION_LIMIT,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
            },
        }

        try:
            state = await graph.aget_state(config)
            # 记忆注入 = 会话级快照（首次调用检索并冻结），不再每轮重搜
            relevant_memory = await self._memory_snapshot(
                user_id=user_id, thread_id=session_id, query=messages[-1].content
            )

            if state.next and self._pending_interrupt(state):
                logger.info("resuming_interrupted_graph", session_id=session_id, next_nodes=state.next)
                response = await graph.ainvoke(
                    Command(resume=messages[-1].content),
                    config=config,
                )
            else:
                # 没有等待人工输入的中断：作为全新提问处理。崩溃遗留的挂起
                # 节点（比如触发递归上限的那次）会被这次新运行自然覆盖，
                # 用户的新消息会真正进入对话线程。
                relevant_memory = relevant_memory or "No relevant memory found."
                response = await graph.ainvoke(
                    input={"messages": dump_messages(messages), "long_term_memory": relevant_memory},
                    config=config,
                )

            # 检查本次调用期间图是否被中断
            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
                logger.info("graph_interrupted", session_id=session_id, interrupt_value=str(interrupt_value))
                return [Message(role="assistant", content=str(interrupt_value))]

            openai_msgs = cast(list[dict], convert_to_openai_messages(response["messages"]))
            _spawn_background(memory_service.add(user_id, openai_msgs, config.get("metadata")))
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
            interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
            logger.info("graph_interrupted", session_id=session_id, interrupt_value=str(interrupt_value))
            return [Message(role="assistant", content=str(interrupt_value))]
        except Exception as e:
            logger.exception("get_response_failed", error=str(e), session_id=session_id)
            raise

    async def get_stream_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """以流式方式从 LLM 获取响应.

        Args:
            messages (list[Message]): 发送给 LLM 的消息列表。
            session_id (str): 会话 ID。
            user_id (Optional[str]): 用户 ID。
            username (Optional[str]): 用户显示名。

        Yields:
            str: LLM 响应的文本片段。
        """
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            # 与非流式路径相同的工具循环上限。
            "recursion_limit": TOOL_LOOP_RECURSION_LIMIT,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
            },
        }
        graph = await self._get_graph()

        try:
            state = await graph.aget_state(config)
            relevant_memory = await self._memory_snapshot(
                user_id=user_id, thread_id=session_id, query=messages[-1].content
            )

            if state.next and self._pending_interrupt(state):
                logger.info("resuming_interrupted_graph_stream", session_id=session_id, next_nodes=state.next)
                graph_input = Command(resume=messages[-1].content)
            else:
                relevant_memory = relevant_memory or "No relevant memory found."
                graph_input = {"messages": dump_messages(messages), "long_term_memory": relevant_memory}

            stream_started = time.perf_counter()
            first_token_at: float | None = None
            async for token, _ in graph.astream(
                graph_input,
                config,
                stream_mode="messages",
            ):
                if not isinstance(token, (AIMessage, AIMessageChunk)):
                    continue

                text = extract_text_content(token.content)
                if text:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                        logger.info(
                            "llm_ttft",
                            ttft_ms=round((first_token_at - stream_started) * 1000, 1),
                            session_id=session_id,
                        )
                    yield text

            # 流结束后：检查是否中断，否则更新长期记忆
            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
                logger.info("graph_interrupted_stream", session_id=session_id, interrupt_value=str(interrupt_value))
                yield str(interrupt_value)
            elif state.values and "messages" in state.values:
                openai_msgs = cast(list[dict], convert_to_openai_messages(state.values["messages"]))
                _spawn_background(memory_service.add(user_id, openai_msgs, config.get("metadata")))
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
            logger.info("graph_interrupted_stream", session_id=session_id, interrupt_value=str(interrupt_value))
            yield str(interrupt_value)
        except GraphRecursionError:
            # 工具循环打满上限：向流式客户端推送一句可理解的提示，而不是 500
            logger.warning("graph_recursion_limit_hit_stream", session_id=session_id)
            yield "抱歉，这个问题需要的处理步骤过多，已中途停止。建议把问题拆得更具体一些再试，例如先问某一只基金的情况。"
        except Exception as stream_error:
            logger.exception("stream_processing_failed", error=str(stream_error), session_id=session_id)
            raise stream_error

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

    def __process_messages(self, messages: list[BaseMessage]) -> list[Message]:
        openai_style_messages = convert_to_openai_messages(messages)
        # 只保留 assistant 与 user 两类消息
        return [
            Message(role=message["role"], content=str(message["content"]))
            for message in openai_style_messages
            if message["role"] in ["assistant", "user"] and message["content"]
        ]

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
