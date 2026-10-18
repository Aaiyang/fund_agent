"""多 profile 的 LLM 注册表与运行时模型切换的测试.

FUND_LLM_PROFILES 让多个 OpenAI 兼容的数据源并存，当前用哪个由
LLMService.activate_model 在运行时切换。注册表处理 kwargs 的那条路径必须把调用方
传入的覆盖值和公共默认值合并 —— 早前 ``temperature`` 会被塞进去两次，会话标题生成
就这样直接崩掉。
"""

import json

import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm import LLMRegistry, LLMService
from app.services.llm.registry import _build_registry, _parse_profiles

TWO_PROFILES = [
    {
        "name": "Provider A",
        "model": "model-a",
        "base_url": "https://a.example.com/v1",
        "api_key": "key-a",  # pragma: allowlist secret -- test fixture
    },
    {
        "name": "model-b",
        "model": "model-b",
        "base_url": "https://b.example.com/v1",
        "api_key": "key-b",  # pragma: allowlist secret -- test fixture
    },
]


@pytest.fixture(autouse=True)
def _isolate_profile_sources(tmp_path, monkeypatch):
    """把开发者本机的真实配置文件排除在测试之外（它的优先级高于环境变量）."""
    monkeypatch.setattr(settings, "LLM_PROFILES_FILE", str(tmp_path / "none.json"))


def _with_profiles(monkeypatch, profiles: list | None) -> None:
    monkeypatch.setattr(settings, "LLM_PROFILES_JSON", json.dumps(profiles, ensure_ascii=False) if profiles else "")


def test_parse_profiles_builds_one_entry_per_profile(monkeypatch):
    _with_profiles(monkeypatch, TWO_PROFILES)
    profiles = _parse_profiles()
    assert [p["name"] for p in profiles] == ["Provider A", "model-b"]
    assert [p["model"] for p in profiles] == ["model-a", "model-b"]


def test_parse_profiles_invalid_json_falls_back_to_flat_config(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROFILES_JSON", "{not json")
    profiles = _parse_profiles()
    assert len(profiles) == 1
    assert profiles[0]["model"] == settings.DEFAULT_LLM_MODEL
    assert profiles[0]["base_url"] == settings.OPENAI_BASE_URL


def test_parse_profiles_missing_fields_rejected(monkeypatch):
    _with_profiles(monkeypatch, [{"name": "broken", "model": "m"}])
    profiles = _parse_profiles()
    assert len(profiles) == 1
    assert profiles[0]["model"] == settings.DEFAULT_LLM_MODEL


def test_registry_builds_entries_and_keeps_model_ids(monkeypatch):
    _with_profiles(monkeypatch, TWO_PROFILES)
    entries = _build_registry()
    assert [e["name"] for e in entries] == ["Provider A", "model-b"]
    assert [e["model"] for e in entries] == ["model-a", "model-b"]
    assert all(isinstance(e["llm"], ChatOpenAI) for e in entries)


def test_get_with_kwargs_merges_without_duplicate_temperature(monkeypatch):
    _with_profiles(monkeypatch, TWO_PROFILES)
    entries = _build_registry()
    monkeypatch.setattr(LLMRegistry, "LLMS", entries)

    # 回归用例：`temperature` 以前会被传两次（默认值加覆盖值），抛 TypeError，
    # 后台的会话标题生成随之整个失败。
    llm = LLMRegistry.get("model-b", temperature=0.3, max_tokens=32)
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "model-b"
    assert llm.temperature == 0.3


def test_default_index_matches_profile_name_then_model_id(monkeypatch):
    _with_profiles(monkeypatch, TWO_PROFILES)
    entries = _build_registry()
    monkeypatch.setattr(LLMRegistry, "LLMS", entries)

    # DEFAULT_LLM_MODEL 在这里匹配不到任何 profile 名；兜底改去匹配模型 id，
    # 匹配不到就落在下标 0。
    assert LLMRegistry.default_index() == 0

    entries_with_default = [dict(e) for e in entries]
    entries_with_default[1]["model"] = settings.DEFAULT_LLM_MODEL
    monkeypatch.setattr(LLMRegistry, "LLMS", entries_with_default)
    assert LLMRegistry.default_index() == 1


def test_service_activate_model_switches_at_runtime(monkeypatch):
    _with_profiles(monkeypatch, TWO_PROFILES)
    entries = _build_registry()
    monkeypatch.setattr(LLMRegistry, "LLMS", entries)

    service = LLMService()
    assert service.active_model_name() == "Provider A"

    service.activate_model("model-b")
    assert service.active_model_name() == "model-b"
    assert service.get_llm() is LLMRegistry.LLMS[1]["llm"]

    with pytest.raises(ValueError, match="not found in registry"):
        service.activate_model("no-such-provider")


def test_structured_output_binds_through_function_calling_not_json_mode():
    """GLM-5.3 在 json_mode 下会思考完再回空正文.

    实测报错：ValueError: expected value at line 1 column 1。

    工具调用那条路径主对话已经在用，所以结构化输出必须显式走 function_calling，
    否则多角色研究的三个角色与审核会整批失败。
    """
    from app.services.llm.service import _with_schema

    class Recorder:
        def with_structured_output(self, schema, **kwargs):
            self.called = (schema, kwargs)
            return self

    class Schema(BaseModel):
        answer: str = ""

    model = Recorder()
    assert _with_schema(model, None) is model
    assert _with_schema(model, Schema) is model
    assert model.called == (Schema, {"method": "function_calling", "include_raw": True})


def test_structured_parsing_error_becomes_a_classified_contract_violation():
    """模型回了话但字段不合：要报成契约问题，不能和"连接中断"混成一类."""
    from pydantic import BaseModel as _BaseModel

    from app.services.llm.service import _unwrap_structured
    from app.services.llm.timeouts import LLMContractViolation

    class Answer(_BaseModel):
        text: str

    assert _unwrap_structured(Answer(text="ok")) is not None
    assert _unwrap_structured("非结构化响应") == "非结构化响应"
    parsed = _unwrap_structured({"raw": None, "parsed": Answer(text="ok"), "parsing_error": None})
    assert parsed.text == "ok"
    with pytest.raises(LLMContractViolation) as error:
        _unwrap_structured({"raw": None, "parsed": None, "parsing_error": "text: Field required"})
    assert error.value.reason == "contract" and "Field required" in str(error.value)


def test_missing_tool_call_is_a_contract_violation_not_a_crash():
    """模型改用普通文本作答时 parsed 为空：要报成契约问题，让回喂重试有机会接住."""
    from langchain_core.messages import AIMessage

    from app.services.llm.service import _unwrap_structured
    from app.services.llm.timeouts import LLMContractViolation

    prose = "这是一段没有走工具调用的回答。" * 30
    with pytest.raises(LLMContractViolation) as error:
        _unwrap_structured({"raw": AIMessage(content=prose), "parsed": None, "parsing_error": None})
    assert error.value.reason == "contract"
    assert str(len(prose)) in error.value.field_errors, "要留下可诊断的线索：写了多少字"


async def test_structured_call_reports_usage_from_the_raw_message(monkeypatch):
    """include_raw 的价值之一：结构化调用的 token 不再是日志里的一串 None."""
    from langchain_core.messages import AIMessage

    from app.services.llm import service as service_module
    from app.services.llm.timeouts import LLMCallProgress, call_progress

    class Answer(BaseModel):
        text: str

    class RawLLM:
        async def ainvoke(self, messages, config=None):
            return {
                "raw": AIMessage(
                    content='{"text":"ok"}',
                    usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
                ),
                "parsed": Answer(text="ok"),
                "parsing_error": None,
            }

    progress = LLMCallProgress(idle_timeout=60)
    token = call_progress.set(progress)
    try:
        result = await service_module.LLMService()._invoke_with_retry(RawLLM(), [])
    finally:
        call_progress.reset(token)
    assert result.text == "ok"
    assert progress.structured_usage["input_tokens"] == 7 and progress.structured_usage["output_tokens"] == 3
