"""供应商档案响应必须支持任意数量的配置，且只返回掩码密钥."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.agent import _llm_profiles_response, router
from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.limiter import limiter
from app.services.llm import LLMRegistry, llm_service, profile_store


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_profiles_response_keeps_each_profile_fields_and_masks_keys(monkeypatch, count: int) -> None:
    entries = [
        {
            "name": f"provider-{index}",
            "model": f"model-{index}",
            "base_url": f"https://provider-{index}.example.com/v1",
            "api_key": f"fixture-key-{index}",  # pragma: allowlist secret -- test fixture
        }
        for index in range(count)
    ]
    monkeypatch.setattr(LLMRegistry, "LLMS", entries)
    monkeypatch.setattr(llm_service, "active_model_name", lambda: entries[-1]["name"])

    response = _llm_profiles_response()

    assert response.active == entries[-1]["name"]
    assert [item.model_dump(exclude={"request_id"}) for item in response.profiles] == [
        {
            "name": entry["name"],
            "model": entry["model"],
            "base_url": entry["base_url"],
            "key_hint": profile_store.key_hint(entry["api_key"]),
        }
        for entry in entries
    ]
    assert all(entry["api_key"] not in response.model_dump_json() for entry in entries)

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/agent")
    app.dependency_overrides[get_current_identity] = lambda: AuthIdentity(user_id=1)
    with TestClient(app) as client:
        result = client.get("/agent/llm/profiles")
    assert result.status_code == 200
    payload = result.json()
    assert payload["active"] == entries[-1]["name"]
    assert [item["name"] for item in payload["profiles"]] == [entry["name"] for entry in entries]
    assert all(entry["api_key"] not in result.text for entry in entries)
