"""个人模型的加密载荷、HTTP 接口和用户隔离回归测试."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.agent import router
from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.services.llm.credentials import decrypt_key
from app.services.llm.registry import LLMRegistry
from app.services.llm import user_profiles
from app.services.llm.user_profiles import DEFAULT_PROFILE_NAME, PersonalProfile, user_profile_service


class MemoryRepository:
    def __init__(self):
        self.rows = {}

    async def get(self, user_id):
        return self.rows.get(user_id)

    async def save(self, user_id, profiles, active):
        self.rows[user_id] = SimpleNamespace(profiles=profiles, active=active)

    async def set_active(self, user_id, name):
        row = self.rows.get(user_id)
        if name != DEFAULT_PROFILE_NAME and (row is None or name not in {p["name"] for p in row.profiles}):
            return False
        if row:
            row.active = name
        return True


@pytest.fixture
def repository(monkeypatch):
    repo = MemoryRepository()
    monkeypatch.setattr(user_profiles, "user_llm_repository", repo)
    monkeypatch.setattr(settings, "LLM_PROFILE_ENCRYPTION_KEY", "fixture-master")
    monkeypatch.setattr(settings, "BASIC_LLM_API_KEY", "fixture-basic")
    return repo


def personal(name="personal", key="fixture-private", url="https://personal.example/v1"):
    return PersonalProfile(name=name, model="personal-model", base_url=url, api_key=key)


def test_basic_key_fallback_requires_both_model_and_endpoint_match(repository, monkeypatch):
    monkeypatch.setattr(settings, "BASIC_LLM_API_KEY", "")
    matching = {
        "model": settings.BASIC_LLM_MODEL,
        "base_url": settings.BASIC_LLM_BASE_URL,
        "api_key": "fixture-basic",  # pragma: allowlist secret -- test fixture
    }
    monkeypatch.setattr(
        LLMRegistry,
        "LLMS",
        [
            {
                **matching,
                "base_url": "https://other.example",
                "api_key": "fixture-other",  # pragma: allowlist secret
            },
            matching,
        ],
    )
    assert user_profiles.basic_profile().api_key == "fixture-basic"  # pragma: allowlist secret
    monkeypatch.setattr(LLMRegistry, "LLMS", [{**matching, "model": "another-model"}])
    assert user_profiles.basic_profile().api_key == ""


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
async def test_profiles_are_encrypted_and_scoped_to_owner(repository, count):
    profiles = [personal(name=f"provider-{i}", key=f"fixture-key-{i}") for i in range(count)]
    response = await user_profile_service.save_profiles(1, profiles)
    assert len(response.profiles) == count + 1
    assert response.profiles[0].read_only and response.profiles[0].key_hint == ""
    assert all(p.api_key not in response.model_dump_json() for p in profiles)
    for saved, profile in zip(repository.rows[1].profiles, profiles, strict=True):
        assert "api_key" not in saved
        assert profile.api_key not in saved["encrypted_api_key"]
        assert decrypt_key(1, saved["encrypted_api_key"]) == profile.api_key
        with pytest.raises(RuntimeError, match="无法解密"):
            decrypt_key(2, saved["encrypted_api_key"])
    other = await user_profile_service.list_profiles(2)
    assert [p.name for p in other.profiles] == [DEFAULT_PROFILE_NAME]


async def test_save_blank_key_retains_only_same_users_same_endpoint(repository):
    await user_profile_service.save_profiles(1, [personal()])
    await user_profile_service.save_profiles(1, [personal(key="")])
    assert (await user_profile_service._load(1))[0][
        0
    ].api_key == "fixture-private"  # pragma: allowlist secret -- test fixture
    with pytest.raises(ValueError, match="需要填写"):
        await user_profile_service.save_profiles(2, [personal(key="")])
    with pytest.raises(ValueError, match="重新填写"):
        await user_profile_service.save_profiles(1, [personal(key="", url="https://other.example/v1")])


async def test_switch_and_execution_never_use_another_users_config(repository):
    await user_profile_service.save_profiles(1, [personal("A")])
    await user_profile_service.save_profiles(2, [personal("B")])
    await user_profile_service.switch_profile(1, "A")
    with pytest.raises(ValueError, match="当前用户"):
        await user_profile_service.switch_profile(2, "A")
    assert [p["name"] for p in await user_profile_service.execution_profiles(1)] == ["A", DEFAULT_PROFILE_NAME]
    assert [p["name"] for p in await user_profile_service.execution_profiles(2)] == [DEFAULT_PROFILE_NAME]
    response = await user_profile_service.save_profiles(1, [])
    assert response.active == DEFAULT_PROFILE_NAME
    assert len(response.profiles) == 1
    with pytest.raises(ValueError, match="不能修改"):
        await user_profile_service.save_profiles(1, [personal(DEFAULT_PROFILE_NAME)])


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model",
        "https://user:password@example.com",  # pragma: allowlist secret
        "garbage",
    ],
)
async def test_reject_invalid_endpoint(repository, url):
    with pytest.raises(ValueError, match="HTTP"):
        await user_profile_service.save_profiles(1, [personal(url=url)])
    assert repository.rows == {}


def test_http_settings_and_switch_cannot_modify_global_registry_or_other_user(repository):
    registry_before = list(LLMRegistry.LLMS)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/agent")
    app.dependency_overrides[get_current_identity] = lambda: AuthIdentity(user_id=1)
    with TestClient(app) as client:
        result = client.post("/agent/llm/settings", json={"profiles": [personal().model_dump()]})
        assert result.status_code == 200
        assert "fixture-private" not in result.text
        assert client.post("/agent/llm/switch", json={"name": "personal"}).json()["active"] == "personal"
        app.dependency_overrides[get_current_identity] = lambda: AuthIdentity(user_id=2)
        assert len(client.get("/agent/llm/profiles").json()["profiles"]) == 1
        assert client.post("/agent/llm/switch", json={"name": "personal"}).status_code == 400
        assert (
            client.post("/agent/llm/settings", json={"profiles": [personal(key="").model_dump()]}).status_code == 400
        )
    assert LLMRegistry.LLMS == registry_before
