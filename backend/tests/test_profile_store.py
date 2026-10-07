"""设置页落库层与注册表热重建的测试.

在设置页里编辑的 profile 会写进服务端的一个 JSON 文件，它的优先级高于环境变量；
保存时热重建注册表，当前激活的 profile 如果还在就继续保留它。
"""

import json

import pytest
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.services.llm import LLMRegistry, LLMService
from app.services.llm import profile_store
from app.services.llm.registry import _parse_profiles, _build_registry

PROFILES = [
    {
        "name": "Provider A",
        "model": "model-a",
        "base_url": "https://a.example.com/v1",
        "api_key": "key-a",  # pragma: allowlist secret -- test fixture
    },
    {
        "name": "Provider B",
        "model": "model-b",
        "base_url": "https://b.example.com/v1",
        "api_key": "key-b",  # pragma: allowlist secret -- test fixture
    },
]


@pytest.fixture()
def store_file(tmp_path, monkeypatch):
    path = tmp_path / "profiles.local.json"
    monkeypatch.setattr(settings, "LLM_PROFILES_FILE", str(path))
    monkeypatch.setattr(settings, "LLM_PROFILES_JSON", "")
    return path


def test_profile_store_roundtrip(store_file):
    assert profile_store.load_profiles() == []
    profile_store.save_profiles(PROFILES)
    assert json.loads(store_file.read_text(encoding="utf-8")) == PROFILES
    assert profile_store.load_profiles() == PROFILES


def test_profile_store_broken_file_falls_back_to_empty(store_file):
    store_file.write_text("{broken", encoding="utf-8")
    assert profile_store.load_profiles() == []


def test_key_hint_masks_and_keep_existing_key_merges():
    assert profile_store.key_hint("sk-1234567890") == "sk-1****"
    assert profile_store.key_hint("") == ""
    saved = [{"name": "A", "api_key": "old-key"}]  # pragma: allowlist secret -- test fixture
    merged = profile_store.keep_existing_key({"name": "A", "api_key": ""}, saved)
    assert merged["api_key"] == "old-key"  # pragma: allowlist secret -- test fixture
    untouched = profile_store.keep_existing_key({"name": "A", "api_key": "new"}, saved)  # pragma: allowlist secret
    assert untouched["api_key"] == "new"  # pragma: allowlist secret -- test fixture


def test_keep_existing_key_falls_back_to_registry():
    # 来自环境变量的 profile 只在运行中的注册表里留有密钥；第一次从设置页保存时
    # 不该逼用户把它们重新敲一遍。
    merged = profile_store.keep_existing_key(
        {"name": "EnvProfile", "api_key": ""},
        saved=[],
        fallback_keys={"EnvProfile": "env-key"},  # pragma: allowlist secret -- test fixture
    )
    assert merged["api_key"] == "env-key"  # pragma: allowlist secret -- test fixture
    missing = profile_store.keep_existing_key(
        {"name": "Unknown", "api_key": ""}, saved=[], fallback_keys={"EnvProfile": "env-key"}
    )
    assert missing["api_key"] == ""


def test_parse_profiles_prefers_file_over_env(store_file, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROFILES_JSON", json.dumps(PROFILES))
    assert [p["name"] for p in _parse_profiles()] == ["Provider A", "Provider B"]

    file_profiles = [dict(PROFILES[0], name="FromFile")]
    profile_store.save_profiles(file_profiles)
    assert [p["name"] for p in _parse_profiles()] == ["FromFile"]


def test_registry_rebuild_replaces_entries(monkeypatch):
    monkeypatch.setattr(LLMRegistry, "LLMS", _build_registry())
    names = LLMRegistry.rebuild(PROFILES)

    assert names == ["Provider A", "Provider B"]
    assert LLMRegistry.get_all_names() == names
    assert LLMRegistry.LLMS[1]["model"] == "model-b"
    assert isinstance(LLMRegistry.get("Provider B"), ChatOpenAI)


def test_registry_rebuild_rejects_bad_profiles():
    with pytest.raises(ValueError, match="at least one profile"):
        LLMRegistry.rebuild([])
    with pytest.raises(ValueError, match="duplicate profile name"):
        LLMRegistry.rebuild([dict(PROFILES[0]), dict(PROFILES[0])])
    with pytest.raises(ValueError, match="missing fields"):
        LLMRegistry.rebuild([{"name": "x", "model": "m"}])


def test_service_refresh_preserves_name_when_profiles_are_reordered(monkeypatch):
    monkeypatch.setattr(LLMRegistry, "LLMS", [])
    LLMRegistry.rebuild(PROFILES)
    service = LLMService()
    service.activate_model("Provider B")
    active_name = service.active_model_name()

    LLMRegistry.rebuild(list(reversed(PROFILES)))
    service.refresh_profiles(active_name=active_name)

    assert service.active_model_name() == "Provider B"
    assert service.get_llm() is LLMRegistry.get("Provider B")


def test_service_refresh_keeps_active_profile(monkeypatch):
    entries = [
        {
            "name": p["name"],
            "model": p["model"],
            "base_url": p["base_url"],
            "api_key": p["api_key"],
            "llm": object(),  # refresh/activate 只搬运引用，不真正调用
        }
        for p in PROFILES
    ]
    monkeypatch.setattr(LLMRegistry, "LLMS", entries)
    service = LLMService()
    service.activate_model("Provider B")

    # 名字不变但实例是全新的：当前激活的 profile 会落到新的那一条引用上。
    fresh = [dict(e, llm=object()) for e in entries]
    names = LLMRegistry.rebuild(PROFILES)
    monkeypatch.setattr(LLMRegistry, "LLMS", fresh)
    result = service.refresh_profiles()
    assert result == names
    assert service.active_model_name() == "Provider B"

    # 激活的那条被删掉了：退回默认条目。
    monkeypatch.setattr(LLMRegistry, "LLMS", [dict(fresh[0])])
    service.refresh_profiles()
    assert service.active_model_name() == "Provider A"
