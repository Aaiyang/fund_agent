"""多 profile 的 LLM 注册表与运行时模型切换的测试.

FUND_LLM_PROFILES 让多个 OpenAI 兼容的数据源并存，当前用哪个由
LLMService.activate_model 在运行时切换。注册表处理 kwargs 的那条路径必须把调用方
传入的覆盖值和公共默认值合并 —— 早前 ``temperature`` 会被塞进去两次，会话标题生成
就这样直接崩掉。
"""

import json

import pytest
from langchain_openai import ChatOpenAI

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
