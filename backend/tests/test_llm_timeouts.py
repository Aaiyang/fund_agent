"""真实 LangChain 流式回调上的超时、降级及取消回归，不调用外部模型."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from openai import APITimeoutError
from tenacity import wait_none
from typing_extensions import TypedDict

from app.core.config import settings
from app.services.llm import service as service_module
from app.services.llm.registry import _build_chat_model
from app.services.llm.service import LLMService
from app.services.llm.timeouts import LLMResponseInterrupted, call_progress


class TimedStreamModel(FakeMessagesListChatModel):
    fragments: list[AIMessageChunk]
    delays: list[float]
    calls: int = 0
    active: bool = False
    fail_after: bool = False
    fail_before_attempts: int = 0

    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.calls += 1
        self.active = True
        try:
            if self.calls <= self.fail_before_attempts:
                raise APITimeoutError(request=httpx.Request("POST", "https://fixture.invalid/"))
            for delay, fragment in zip(self.delays, self.fragments, strict=True):
                await asyncio.sleep(delay)
                yield ChatGenerationChunk(message=fragment)
            if self.fail_after:
                raise APITimeoutError(request=httpx.Request("POST", "https://fixture.invalid/"))
        finally:
            self.active = False


class StreamRecorder(BaseCallbackHandler):
    run_inline = True

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.metadata: list[dict] = []

    def on_chat_model_start(self, serialized: Any, messages: Any, *, metadata: Any = None, **kwargs: Any) -> None:
        self.metadata.append(metadata or {})

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self.tokens.append(token)


class ChatState(TypedDict):
    answer: str


class VendorReasoningStream(httpx.AsyncByteStream):
    def __init__(self, answer: str = "answer", tool: str | None = None) -> None:
        self.closed = False
        self.answer = answer
        # 结构化输出走 function_calling 时，正文不在 content 里，而是工具调用的 arguments。
        self.tool = tool

    async def __aiter__(self):
        """模拟供应商通过 SSE 先返回推理，再返回最终正文."""
        final = (
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "fixture-call",
                        "type": "function",
                        "function": {"name": self.tool, "arguments": self.answer},
                    }
                ]
            }
            if self.tool
            else {"content": self.answer}
        )
        deltas = [{"reasoning_content": "hidden reasoning"}] * 7 + [final]
        for index, delta in enumerate(deltas):
            await asyncio.sleep(0.045)
            event = {
                "id": "fixture-completion",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", **delta} if index == 0 else delta,
                        "finish_reason": ("tool_calls" if self.tool else "stop") if index == len(deltas) - 1 else None,
                    }
                ],
            }
            yield ("data: " + json.dumps(event) + "\n\n").encode()
        yield b"data: [DONE]\n\n"

    async def aclose(self) -> None:
        self.closed = True


def stream(texts: list[str], delays: list[float], **kwargs: Any) -> TimedStreamModel:
    return TimedStreamModel(
        responses=[AIMessage(content="unused")],
        fragments=[AIMessageChunk(content=text) for text in texts],
        delays=delays,
        **kwargs,
    )


@pytest.fixture
def service_factory(monkeypatch):
    monkeypatch.setattr(settings, "LLM_REQUEST_TIMEOUT", 0.18)
    monkeypatch.setattr(settings, "LLM_STREAM_IDLE_TIMEOUT", 0.12)
    monkeypatch.setattr(settings, "LLM_TOTAL_TIMEOUT", 1.5)

    def build(models: dict[str, TimedStreamModel]):
        monkeypatch.setattr(
            service_module, "_build_chat_model", lambda model, *_args, **_kwargs: models[model].bind(stream=True)
        )
        profiles = [
            {
                "name": name,
                "model": name,
                "api_key": "fixture",  # pragma: allowlist secret
                "base_url": "https://fixture.invalid/v1",
            }
            for name in models
        ]
        return LLMService(), profiles

    return build


async def test_progress_extends_stream_beyond_initial_wait(service_factory):
    model = stream(["a"] * 8, [0.045] * 8)
    service, profiles = service_factory({"slow": model})
    with service.use_profiles(profiles):
        result = await service.call("question")
    assert result.content == "a" * 8
    assert model.calls == 1 and not model.active
    assert call_progress.get() is None


async def test_silent_first_model_switches_without_same_model_retry(service_factory):
    slow = stream(["late"], [0.5])
    backup = stream(["ok"], [0.005])
    service, profiles = service_factory({"slow": slow, "backup": backup})
    with service.use_profiles(profiles):
        result = await service.call("question")
        assert service.active_model_name() == "backup"
    assert result.content == "ok"
    assert slow.calls == backup.calls == 1
    assert not slow.active and call_progress.get() is None


async def test_transient_upstream_error_before_output_still_retries(service_factory, monkeypatch):
    model = stream(["ok"], [0.005], fail_before_attempts=1)
    backup = stream(["backup"], [0.005])
    service, profiles = service_factory({"model": model, "backup": backup})
    # 仅移除测试的退避等待；生产保持 tenacity 指数退避及尝试次数。
    invoke = LLMService._invoke_with_retry.retry_with(wait=wait_none())
    monkeypatch.setattr(service, "_invoke_with_retry", invoke.__get__(service, LLMService))
    with service.use_profiles(profiles):
        result = await service.call("question")
    assert result.content == "ok"
    assert model.calls == 2 and backup.calls == 0


@pytest.mark.parametrize("failure", ["idle", "upstream"])
async def test_partial_output_never_retries_or_mixes_fallback(service_factory, failure):
    interrupted = stream(
        ["partial"] if failure == "upstream" else ["partial", "late"],
        [0.005] if failure == "upstream" else [0.005, 0.4],
        fail_after=failure == "upstream",
    )
    backup = stream(["different answer"], [0.005])
    service, profiles = service_factory({"interrupted": interrupted, "backup": backup})
    recorder = StreamRecorder()

    async def invoke(_: str):
        with service.use_profiles(profiles):
            return await service.call("question")

    with pytest.raises(LLMResponseInterrupted) as error:
        await RunnableLambda(invoke).ainvoke("question", config={"callbacks": [recorder]})
    assert error.value.reason == failure
    assert "".join(recorder.tokens) == "partial"
    assert interrupted.calls == 1 and backup.calls == 0
    assert not interrupted.active and call_progress.get() is None


async def test_continuous_output_still_obeys_total_cap(service_factory, monkeypatch):
    model = stream(["a"] * 30, [0.035] * 30)
    service, profiles = service_factory({"slow": model})
    monkeypatch.setattr(settings, "LLM_TOTAL_TIMEOUT", 0.23)
    with service.use_profiles(profiles):
        with pytest.raises(LLMResponseInterrupted) as error:
            await service.call("question")
    assert error.value.reason == "total"
    assert model.calls == 1 and not model.active
    assert call_progress.get() is None


async def test_empty_heartbeats_do_not_extend_deadline(service_factory):
    model = stream([""] * 15 + ["late"], [0.03] * 16)
    backup = stream(["ok"], [0.005])
    service, profiles = service_factory({"empty": model, "backup": backup})
    with service.use_profiles(profiles):
        result = await service.call("question")
    assert result.content == "ok"
    assert model.calls == backup.calls == 1 and not model.active


@pytest.mark.parametrize("kind", ["tool", "reasoning"])
async def test_tool_arguments_and_reasoning_count_as_progress(service_factory, kind):
    fragments = [AIMessageChunk(content="", additional_kwargs={"reasoning_content": "thinking"}) for _ in range(7)]
    if kind == "tool":
        fragments = [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "lookup" if index == 0 else None,
                        "id": "call-1" if index == 0 else None,
                        "args": piece,
                        "index": 0,
                    }
                ],
            )
            for index, piece in enumerate(['{"', "code", '":', '"', "00", "001", '"}'])
        ]
    model = TimedStreamModel(responses=[AIMessage(content="unused")], fragments=fragments, delays=[0.045] * 7)
    service, profiles = service_factory({"slow": model})
    with service.use_profiles(profiles):
        result = await service.call("question")
    assert model.calls == 1 and not model.active
    if kind == "tool":
        assert result.tool_calls[0]["args"] == {"code": "00001"}


async def test_original_callbacks_and_identity_metadata_are_preserved(service_factory):
    model = stream(["one", "two"], [0.005, 0.005])
    service, profiles = service_factory({"model": model})
    recorder = StreamRecorder()

    async def invoke(_: str):
        with service.use_profiles(profiles):
            return await service.call("question")

    result = await RunnableLambda(invoke).ainvoke(
        "question", config={"callbacks": [recorder], "metadata": {"user_id": "fixture-user"}}
    )
    assert result.content == "onetwo"
    assert "".join(recorder.tokens) == "onetwo"
    assert recorder.metadata[0]["user_id"] == "fixture-user"


async def test_langgraph_implicit_streaming_extends_deadline(service_factory, monkeypatch):
    model = stream(["a"] * 8, [0.045] * 8)
    service, profiles = service_factory({"model": model})
    # 不显式开启 streaming，复现项目 ainvoke + LangGraph 消息回调的真实入口。
    monkeypatch.setattr(service_module, "_build_chat_model", lambda *_args, **_kwargs: model)

    async def chat(state: ChatState) -> dict:
        result = await service.call("question")
        return {"answer": result.content}

    builder = StateGraph(ChatState)
    builder.add_node("chat", chat)
    builder.add_edge(START, "chat")
    builder.add_edge("chat", END)
    graph = builder.compile()
    with service.use_profiles(profiles):
        chunks = [chunk async for chunk, _metadata in graph.astream({"answer": ""}, stream_mode="messages")]
    assert "".join(chunk.content for chunk in chunks) == "a" * 8
    assert model.calls == 1 and not model.active


async def test_external_cancellation_is_not_relabelled_as_timeout(service_factory):
    model = stream(["late"], [0.5])
    service, profiles = service_factory({"model": model})
    with service.use_profiles(profiles):
        task = asyncio.create_task(service.call("question"))
        for _ in range(30):
            if model.active:
                break
            await asyncio.sleep(0.005)
        assert model.active
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not model.active and call_progress.get() is None


async def test_concurrent_streams_have_independent_deadlines_and_profiles(service_factory):
    silent = stream(["late"], [0.5])
    healthy = stream(["ok"] * 8, [0.045] * 8)
    service, profiles = service_factory({"silent": silent, "healthy": healthy})

    async def invoke(profile):
        with service.use_profiles([profile]):
            return await service.call("question")

    failed, succeeded = await asyncio.gather(invoke(profiles[0]), invoke(profiles[1]), return_exceptions=True)
    assert isinstance(failed, RuntimeError)
    assert succeeded.content == "ok" * 8
    assert silent.calls == healthy.calls == 1
    assert not silent.active and not healthy.active and call_progress.get() is None


def test_sdk_retries_disabled_to_avoid_nested_retry_budget():
    model = _build_chat_model("fixture", "fixture", "https://fixture.invalid/v1")
    assert model.max_retries == 0
    assert model.request_timeout == settings.LLM_REQUEST_TIMEOUT


class StructuredAnswer(BaseModel):
    """真实 SDK 结构化输出也必须在恢复任务时观察到流式进度."""

    answer: str


@pytest.mark.parametrize("structured", [False, True])
async def test_vendor_reasoning_progress_survives_actual_sdk_and_adapter(service_factory, monkeypatch, structured):
    service, profiles = service_factory({"fixture": stream(["unused"], [0.005])})
    wire_stream = VendorReasoningStream(
        '{"answer":"answer"}' if structured else "answer", tool="StructuredAnswer" if structured else None
    )
    requests = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=wire_stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = _build_chat_model("fixture", "fixture", "https://fixture.invalid/v1", http_async_client=client)
        monkeypatch.setattr(service_module, "_build_chat_model", lambda *_args, **_kwargs: model)
        with service.use_profiles(profiles):
            result = (
                await service.call("question", response_format=StructuredAnswer, max_tokens=256)
                if structured
                else await service.call("question")
            )
    if structured:
        assert isinstance(result, StructuredAnswer) and result.answer == "answer"
    else:
        assert result.content == "answer"
        assert result.response_metadata["fund_reasoning_chars"] > 0
    assert "hidden reasoning" not in result.model_dump_json()
    assert len(requests) == 1 and requests[0]["stream"] is True
    assert wire_stream.closed
