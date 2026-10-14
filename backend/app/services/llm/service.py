"""LLM service with retries, circular fallback, and optional structured output."""

import asyncio
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from collections.abc import Iterator
from typing import (
    Any,
    Callable,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    overload,
)

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables.config import ensure_config, merge_configs
from openai import (
    APIError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.registry import LLMRegistry, _build_chat_model
from app.services.llm.timeouts import LLMCallProgress, LLMResponseInterrupted, LLMStartTimeout, call_progress

T = TypeVar("T", bound=BaseModel)


@dataclass
class RequestModels:
    """单次请求的模型与降级位置，不共享用户选择."""

    profiles: list[dict[str, str]]
    models: list[Any]
    index: int = 0


_REQUEST_MODELS: ContextVar[RequestModels | None] = ContextVar("request_models", default=None)


def _retryable_llm_error(error: BaseException) -> bool:
    """首段等待耗尽直接降级，已有输出的中断不进入重试."""
    return isinstance(error, (RateLimitError, APITimeoutError, APIError)) and not isinstance(error, LLMStartTimeout)


def _with_schema(model: Any, response_format: Optional[Type[BaseModel]]) -> Any:
    """按工具调用方式绑定结构化输出，不用 json_mode.

    实测（智谱 GLM-5.3-flash，同一角色 prompt）：默认解析出的 ``json_mode`` 会在思考
    之后回一段空正文，LangChain 聚合时对空串做 JSON 解析直接 ``ValueError: expected
    value at line 1 column 1``，三个研究角色与审核全挂；换成 ``function_calling``
    同一个请求能拿到完整对象。工具调用这条路径主对话早就在用，厂商兼容性已被验证。
    """
    return model.with_structured_output(response_format, method="function_calling") if response_format else model


class LLMService:
    """Service for managing LLM calls with retries and circular fallback.

    Two distinct execution paths:

    - **Default path** (no model_name / response_format / model_kwargs): uses
      ``self._llm`` which is the tool-bound agent model. Circular fallback
      updates ``self._llm`` so tool bindings are preserved across retries.

    - **One-off path** (any override provided): resolves a fresh, local
      ``Runnable`` for the call without ever touching ``self._llm``, so
      concurrent default-path calls are never affected.
    """

    def __init__(self) -> None:
        """按配置里的默认模型初始化 LLM 服务."""
        self._llm: Any = None  # BaseChatModel pre-bind_tools, Runnable after
        self._current_model_index: int = 0
        self._bound_tools: List = []

        all_names = LLMRegistry.get_all_names()
        try:
            self._current_model_index = LLMRegistry.default_index()
            self._llm = LLMRegistry.get_model_at_index(self._current_model_index)["llm"]
            logger.info(
                "llm_service_initialized",
                default_model=settings.DEFAULT_LLM_MODEL,
                model_index=self._current_model_index,
                total_models=len(all_names),
                environment=settings.ENVIRONMENT.value,
            )
        except Exception as e:
            self._current_model_index = 0
            self._llm = LLMRegistry.LLMS[0]["llm"]
            logger.warning(
                "default_model_not_found_using_first",
                requested=settings.DEFAULT_LLM_MODEL,
                using=all_names[0] if all_names else "none",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        response_format: None = ...,
        **model_kwargs: Any,
    ) -> BaseMessage: ...

    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        *,
        response_format: Type[T],
        **model_kwargs: Any,
    ) -> T: ...

    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        **model_kwargs: Any,
    ) -> Union[BaseMessage, BaseModel]:
        """Call the LLM with retries and circular fallback.

        Args:
            messages: Conversation messages to send.
            model_name: Override the model. ``None`` uses the current default.
            response_format: Pydantic schema for structured output. When
                provided the call chains ``.with_structured_output(schema,
                method="function_calling")`` and returns a validated instance
                of that schema instead of a raw ``BaseMessage``.
            on_text: Optional observer receiving each streamed fragment
                (reasoning first, then answer text) for a live one-line progress
                display. It never changes what the call returns.
            **model_kwargs: Extra kwargs forwarded to ``LLMRegistry.get`` when
                constructing a one-off model instance (e.g. ``temperature``,
                ``max_tokens``, ``reasoning``).

        Returns:
            ``BaseMessage`` when ``response_format`` is ``None``, otherwise a
            validated instance of ``response_format``.

        Raises:
            RuntimeError: When all models fail after retries or the total
                timeout budget is exceeded.
        """
        progress = LLMCallProgress(settings.LLM_STREAM_IDLE_TIMEOUT, on_text=on_text)
        progress_token = call_progress.set(progress)
        total_deadline = asyncio.timeout(settings.LLM_TOTAL_TIMEOUT)
        try:
            async with total_deadline:
                result = await self._call_with_fallback(messages, model_name, response_format, model_kwargs)
            metadata = result.response_metadata if isinstance(result, BaseMessage) else {}
            usage = getattr(result, "usage_metadata", None) or {}
            logger.info(
                "llm_call_completed",
                finish_reason=metadata.get("finish_reason"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                **progress.diagnostics(),
            )
            return result
        except asyncio.TimeoutError:
            if not total_deadline.expired():
                raise
            logger.exception(
                "llm_total_timeout_exceeded",
                timeout_seconds=settings.LLM_TOTAL_TIMEOUT,
                **progress.diagnostics(),
            )
            raise LLMResponseInterrupted("total")
        except Exception as exc:
            logger.exception(
                "llm_call_failed",
                failure_reason=getattr(exc, "reason", type(exc).__name__),
                **progress.diagnostics(),
            )
            raise
        finally:
            call_progress.reset(progress_token)

    def get_llm(self) -> Any:
        """Return the current tool-bound default LLM instance.

        Returns:
            Current ``BaseChatModel`` instance or ``None`` if not initialised.
        """
        scoped = _REQUEST_MODELS.get()
        if scoped is not None:
            model = scoped.models[scoped.index]
            return model.bind_tools(self._bound_tools) if self._bound_tools else model
        return self._llm

    @contextmanager
    def use_profiles(self, profiles: list[dict[str, str]]) -> Iterator[None]:
        """冻结认证用户本次请求的配置，离开作用域后恢复原上下文."""
        if not profiles:
            raise ValueError("至少需要一个可用模型")
        models = [_build_chat_model(p["model"], p["api_key"], p["base_url"]) for p in profiles]
        token = _REQUEST_MODELS.set(RequestModels(profiles=[dict(p) for p in profiles], models=models))
        try:
            yield
        finally:
            _REQUEST_MODELS.reset(token)

    def active_model_name(self) -> str:
        """返回当前默认模型在注册表里的名称."""
        scoped = _REQUEST_MODELS.get()
        if scoped is not None:
            return scoped.profiles[scoped.index]["name"]
        names = LLMRegistry.get_all_names()
        if 0 <= self._current_model_index < len(names):
            return names[self._current_model_index]
        return names[0] if names else ""

    def activate_model(self, model_name: str) -> None:
        """运行时切换默认的绑工具模型（用于切换厂商）.

        Args:
            model_name: 要激活的注册表 profile 名称。

        Raises:
            ValueError: 该名称没有注册。
        """
        all_names = LLMRegistry.get_all_names()
        if model_name not in all_names:
            raise ValueError(f"model '{model_name}' not found in registry. available models: {', '.join(all_names)}")
        self._current_model_index = all_names.index(model_name)
        self._llm = LLMRegistry.get(model_name)
        if self._bound_tools:
            self._llm = self._llm.bind_tools(self._bound_tools)
        logger.info("llm_model_activated", model=model_name)

    def refresh_profiles(self, active_name: str | None = None) -> List[str]:
        """注册表被重建后，把默认模型重新指向新的条目.

        当前激活的 profile 如果还在，就继续用它（换成新构建的模型条目）；
        不在了就退回配置里的默认条目，默认也没有就取第一条。
        工具绑定会重新应用到新实例上。

        Returns:
            重建后的全部 profile 名称。
        """
        names = LLMRegistry.get_all_names()
        current = active_name if active_name is not None else self.active_model_name()
        if current in names:
            self._current_model_index = names.index(current)
        else:
            self._current_model_index = LLMRegistry.default_index()
            logger.info(
                "llm_active_profile_removed",
                removed=current or "none",
                fallback=names[self._current_model_index] if names else "none",
            )
        self._llm = LLMRegistry.get_model_at_index(self._current_model_index)["llm"]
        if self._bound_tools:
            self._llm = self._llm.bind_tools(self._bound_tools)
        return names

    def bind_tools(self, tools: List) -> "LLMService":
        """Bind tools to the default LLM instance.

        Args:
            tools: List of tools to bind.

        Returns:
            Self for method chaining.
        """
        if self._llm:
            self._bound_tools = tools
            self._llm = self._llm.bind_tools(tools)
            logger.debug("tools_bound_to_llm", tool_count=len(tools))
        return self

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(settings.MAX_LLM_CALL_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_retryable_llm_error),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _invoke_with_retry(self, llm: Any, messages: LanguageModelInput) -> Any:
        """Invoke an LLM runnable with automatic per-model retry logic.

        Args:
            llm: Any LangChain ``Runnable`` (plain model or structured-output chain).
            messages: Messages to send.

        Returns:
            The runnable's response (``BaseMessage`` or a ``BaseModel`` instance).

        Raises:
            OpenAIError: Propagated after all retry attempts are exhausted.
        """
        progress = call_progress.get()
        chunks_before = progress.progress_chunks if progress else 0
        try:
            if progress is None:
                response = await llm.ainvoke(messages)
            else:
                progress.attempts += 1
                deadline = asyncio.timeout(settings.LLM_REQUEST_TIMEOUT)
                progress.deadline = deadline
                try:
                    async with deadline:
                        # 添加观察回调，原 LangGraph 流式、Langfuse 和身份配置保留。
                        config = merge_configs(ensure_config(), {"callbacks": [progress]})
                        response = await llm.ainvoke(messages, config=config)
                except asyncio.TimeoutError:
                    if not deadline.expired():
                        raise
                    if progress.progress_chunks > chunks_before:
                        raise LLMResponseInterrupted("idle")
                    raise LLMStartTimeout()
            logger.debug("llm_call_successful")
            return response
        except (RateLimitError, APITimeoutError, APIError) as e:
            if progress and progress.progress_chunks > chunks_before:
                raise LLMResponseInterrupted("upstream") from e
            logger.warning(
                "llm_attempt_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
                retryable=_retryable_llm_error(e),
            )
            raise
        except OpenAIError as e:
            if progress and progress.progress_chunks > chunks_before:
                raise LLMResponseInterrupted("upstream") from e
            logger.exception(
                "llm_call_failed",
                error_type=type(e).__name__,
                error=str(e),
            )
            raise
        finally:
            if progress:
                progress.deadline = None

    def _switch_to_next_model(self) -> bool:
        """Advance the default model to the next entry in the registry (circular).

        Mutates ``self._llm`` and ``self._current_model_index`` so tool bindings
        survive model switches on the default agent path.

        Returns:
            ``True`` on success, ``False`` if the switch failed.
        """
        try:
            next_index = (self._current_model_index + 1) % len(LLMRegistry.LLMS)
            next_entry = LLMRegistry.get_model_at_index(next_index)
            logger.warning(
                "switching_to_next_model",
                from_index=self._current_model_index,
                to_index=next_index,
                to_model=next_entry["name"],
            )
            self._current_model_index = next_index
            self._llm = next_entry["llm"]
            if self._bound_tools:
                self._llm = self._llm.bind_tools(self._bound_tools)
            logger.info("model_switched", new_model=next_entry["name"], new_index=next_index)
            return True
        except Exception as e:
            logger.error("model_switch_failed", error=str(e))
            return False

    async def _call_with_fallback(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str],
        response_format: Optional[Type[BaseModel]],
        model_kwargs: dict,
    ) -> Union[BaseMessage, BaseModel]:
        """Build path-specific strategies and delegate to the shared fallback loop.

        One-off path (any override set):
            ``get_target`` builds a fresh registry instance each attempt.
            ``advance`` increments a local index — ``self._llm`` is never touched.

        Default path (no overrides):
            ``get_target`` returns ``self._llm`` (tool-bound).
            ``advance`` calls ``_switch_to_next_model`` so bindings persist.
        """
        scoped = _REQUEST_MODELS.get()
        if scoped is not None:
            return await self._call_scoped(messages, scoped, model_name, response_format, model_kwargs)

        def _override_target(idx: int) -> Any:
            base = LLMRegistry.get(LLMRegistry.LLMS[idx]["name"], **model_kwargs)
            return _with_schema(base, response_format)

        def _default_target(_: int) -> Any:
            return self._llm

        def _default_advance(_: int) -> Optional[int]:
            return self._current_model_index if self._switch_to_next_model() else None

        if model_name or response_format or model_kwargs:
            all_names = LLMRegistry.get_all_names()
            if model_name and model_name not in all_names:
                logger.error("requested_model_not_found", model_name=model_name)
                raise ValueError(
                    f"model '{model_name}' not found in registry. available models: {', '.join(all_names)}"
                )

            start = all_names.index(model_name) if model_name else self._current_model_index
            total = len(LLMRegistry.LLMS)
            get_target: Callable[[int], Any] = _override_target

            def _override_advance(idx: int) -> Optional[int]:
                return (idx + 1) % total

            advance: Callable[[int], Optional[int]] = _override_advance
        else:
            start = self._current_model_index
            get_target = _default_target
            advance = _default_advance

        return await self._fallback_loop(messages, start, get_target, advance)

    async def _call_scoped(
        self,
        messages: LanguageModelInput,
        scoped: RequestModels,
        model_name: str | None,
        response_format: Type[BaseModel] | None,
        model_kwargs: dict,
    ) -> Any:
        """请求内重试与降级只访问该用户的模型集合，不改变全局服务."""
        names = [profile["name"] for profile in scoped.profiles]
        if model_name and model_name not in names:
            raise ValueError("未找到本次请求的模型")
        start = names.index(model_name) if model_name else scoped.index
        one_off = bool(model_name or response_format or model_kwargs)
        last_error: Exception | None = None
        for offset in range(len(names)):
            index = (start + offset) % len(names)
            profile = scoped.profiles[index]
            model = (
                _build_chat_model(profile["model"], profile["api_key"], profile["base_url"], **model_kwargs)
                if model_kwargs
                else scoped.models[index]
            )
            if response_format:
                model = _with_schema(model, response_format)
            elif not one_off and self._bound_tools:
                model = model.bind_tools(self._bound_tools)
            try:
                progress = call_progress.get()
                if progress:
                    progress.models_tried.append(profile["model"])
                result = await self._invoke_with_retry(model, messages)
                if not one_off:
                    scoped.index = index
                return result
            except OpenAIError as exc:
                last_error = exc
                logger.warning("user_model_call_failed", model=profile["name"], error_type=type(exc).__name__)
        raise RuntimeError("用户模型与基础模型调用均失败") from last_error

    async def _fallback_loop(
        self,
        messages: LanguageModelInput,
        start: int,
        get_target: Callable[[int], Any],
        advance: Callable[[int], Optional[int]],
    ) -> Any:
        """Shared fallback loop — try each model in turn until one succeeds.

        Args:
            messages: Messages to send.
            start: Registry index to begin from.
            get_target: Returns the ``Runnable`` to invoke for a given index.
            advance: Returns the next index to try, or ``None`` to stop.

        Returns:
            The first successful response.

        Raises:
            RuntimeError: When all models have been exhausted.
        """
        total = len(LLMRegistry.LLMS)
        current = start
        models_tried = 0
        last_error: Optional[Exception] = None

        for models_tried in range(1, total + 1):
            current_name = LLMRegistry.LLMS[current]["name"]
            try:
                progress = call_progress.get()
                if progress:
                    progress.models_tried.append(LLMRegistry.LLMS[current].get("model", current_name))
                return await self._invoke_with_retry(get_target(current), messages)
            except OpenAIError as e:
                last_error = e
                logger.error(
                    "llm_call_failed_after_retries",
                    model=current_name,
                    models_tried=models_tried,
                    total_models=total,
                    error=str(e),
                )
                if models_tried >= total:
                    logger.error(
                        "all_models_failed", models_tried=models_tried, starting_model=LLMRegistry.LLMS[start]["name"]
                    )
                    break
                next_idx = advance(current)
                if next_idx is None:
                    logger.error("failed_to_switch_to_next_model")
                    break
                current = next_idx

        raise RuntimeError(
            f"failed to get response from llm after trying {models_tried} models. last error: {str(last_error)}"
        )


llm_service = LLMService()
