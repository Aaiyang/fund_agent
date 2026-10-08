"""图片聊天导入：真实 LangGraph 中断、人工 HTTP 决策、隔离和上传验证."""

import asyncio
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image

from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.portfolio import get_holding_import, request_holding_import_confirmation
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS
from app.agent.tools.runtime import ToolRuntimeContext, set_tool_runtime
from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from app.core.cache import InMemoryCacheService
from app.core.config import settings
from app.core.limiter import limiter
from app.models.holding_import import HoldingImport
from app.schemas.chat import Message
from app.schemas.holding_import import ImportDetail, ImportItemOut
from app.services import holding_import_service as holding_module
from app.services.agent_holding_import_service import agent_holding_import_service
from app.services.holding_import_service import ImportStateError
from app.services.portfolio_service import AccountNotFoundError
from app.utils.holding_review import holding_review_digest

IMPORT_ID = "a" * 32
SESSION_ID = "image-session"


class ScriptedLLM:
    def __init__(self):
        self.calls = []

    def get_llm(self):
        return SimpleNamespace(model_name="fixture", get_name=lambda: "fixture")

    async def call(self, messages, *args, **kwargs):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_holding_import_confirmation",
                        "args": {"import_id": IMPORT_ID},
                        "id": "image-review",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="已处理人工决策。")


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    state = SimpleNamespace(
        record=HoldingImport(
            id=IMPORT_ID,
            user_id=42,
            account_id=7,
            chat_session_id=SESSION_ID,
            import_type="SCREENSHOT",
            status="REVIEW_REQUIRED",
            image_count=1,
            items_detected=1,
        ),
        item=ImportItemOut(
            id=1,
            matched_fund_code="005827",
            matched_fund_name="示例基金",
            market_value=1000,
            shares=800,
            confidence=0.95,
            validation_status="ok",
        ),
        writes=0,
        cancels=0,
        enqueued=[],
        identity=SimpleNamespace(id=SESSION_ID, user_id=42, name=None, username="fixture"),
    )

    async def get_import(user_id, import_id, **kwargs):
        if import_id == state.record.id and (user_id is None or user_id == state.record.user_id):
            return state.record
        return None

    async def get_detail(user_id, import_id):
        if not await get_import(user_id, import_id):
            return None
        return ImportDetail(
            id=state.record.id,
            account_id=state.record.account_id,
            import_type="SCREENSHOT",
            status=state.record.status,
            image_count=state.record.image_count,
            items_detected=state.record.items_detected,
            items_confirmed=state.record.items_confirmed,
            items=[] if state.record.status in {"PARSING", "CANCELLED"} else [state.item],
        )

    async def confirm(user_id, import_id, *, expected_review_digest=None):
        detail = await get_detail(user_id, import_id)
        if state.record.status == "APPLIED":
            return {"applied": 1, "skipped": 0}
        if expected_review_digest != holding_review_digest(detail):
            raise ImportStateError("import_review_changed")
        state.writes += 1
        state.record.status = "APPLIED"
        state.record.items_confirmed = 1
        return {"applied": 1, "skipped": 0}

    async def cancel(user_id, import_id):
        if state.record.status == "APPLIED":
            raise ImportStateError("applied_import_cannot_be_deleted")
        state.cancels += 1
        state.record.status = "CANCELLED"
        return True

    async def profiles(user_id):
        return [{"name": "basic", "model": "fixture", "api_key": "", "base_url": "https://fixture.example/v1"}]

    monkeypatch.setattr(holding_module.import_repository, "get_import", get_import)
    monkeypatch.setattr(holding_module.holding_import_service, "get_import_detail", get_detail)
    monkeypatch.setattr(holding_module.holding_import_service, "confirm_import", confirm)
    monkeypatch.setattr(holding_module.holding_import_service, "delete_import", cancel)
    monkeypatch.setattr(chatbot.user_profile_service, "execution_profiles", profiles)
    monkeypatch.setattr(chatbot, "cache_service", InMemoryCacheService())
    monkeypatch.setattr(settings, "HOLDING_IMPORT_TEMP_DIR", tmp_path)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(limiter, "enabled", False)
    state.saver = InMemorySaver()
    state.agent = LangGraphAgent()
    state.agent._graph = state.agent._build_graph(state.saver)
    state.llm = ScriptedLLM()
    monkeypatch.setattr(state.agent, "llm_service", state.llm)
    monkeypatch.setattr(chatbot, "agent", state.agent)
    state.app = FastAPI()
    state.app.state.limiter = limiter
    state.app.include_router(chatbot.router, prefix="/chatbot")
    state.app.dependency_overrides[get_current_session] = lambda: state.identity
    return state


async def start_review(client, endpoint="chat"):
    response = await client.post(
        f"/chatbot/{endpoint}",
        json={
            "messages": [{"role": "user", "content": "请同步截图里的持仓"}],
            "holding_import_ids": [IMPORT_ID],
        },
    )
    assert response.status_code == 200, response.text
    if endpoint == "chat/stream":
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["done"] is True
        return events[-1]["pending_action"]
    return response.json()["pending_action"]


@pytest.mark.parametrize("decision", ["confirm", "cancel"])
async def test_real_graph_requires_human_decision_and_is_retry_safe(scenario, decision):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        assert review["kind"] == "holding_import_review" and review["interrupt_id"]
        assert review["items"][0]["market_value"] == 1000
        assert scenario.writes == scenario.cancels == 0
        assert any(IMPORT_ID in str(message.content) for message in scenario.llm.calls[0])
        # 普通聊天和直接调用图都不能将“确认”变成写入。
        blocked = await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "确认"}]})
        assert blocked.status_code == 409
        direct = await scenario.agent.get_response([Message(role="user", content="确认")], SESSION_ID, user_id="42")
        assert "人工复核" in direct[-1].content and len(scenario.llm.calls) == 1
        payload = {
            "decision": decision,
            "interrupt_id": review["interrupt_id"],
            "review_digest": review["review_digest"],
        }
        response = await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
        assert scenario.record.status == ("APPLIED" if decision == "confirm" else "CANCELLED")
        assert response.json()["status"] == scenario.record.status
        assert response.json()["applied"] == (1 if decision == "confirm" else 0)
        assert (scenario.writes, scenario.cancels) == ((1, 0) if decision == "confirm" else (0, 1))
        assert (await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)).status_code == 200
        assert (scenario.writes, scenario.cancels) == ((1, 0) if decision == "confirm" else (0, 1))


async def test_stream_returns_structured_review_in_final_event(scenario):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client, "chat/stream")
        assert review["import_id"] == IMPORT_ID and scenario.writes == 0
        pending = await client.get("/chatbot/pending-action")
        assert pending.json()["pending_action"] == review


async def test_checkpoint_review_recovers_in_new_agent_instance(scenario, monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        original = await start_review(client)
        recovered = LangGraphAgent()
        recovered._graph = recovered._build_graph(scenario.saver)
        monkeypatch.setattr(recovered, "llm_service", scenario.llm)
        monkeypatch.setattr(chatbot, "agent", recovered)
        assert (await client.get("/chatbot/pending-action")).json()["pending_action"] == original


@pytest.mark.parametrize("identity", [(99, SESSION_ID), (42, "another-session")])
async def test_cross_user_or_session_cannot_attach_read_or_approve(scenario, identity):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        scenario.identity.user_id, scenario.identity.id = identity
        assert (await client.get(f"/chatbot/holding-imports/{IMPORT_ID}")).status_code == 404
        attached = await client.post(
            "/chatbot/chat",
            json={
                "messages": [{"role": "user", "content": "同步持仓"}],
                "holding_import_ids": [IMPORT_ID],
            },
        )
        assert attached.status_code == 404
        response = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": "confirm",
                "interrupt_id": review["interrupt_id"],
                "review_digest": review["review_digest"],
            },
        )
        assert response.status_code == 404 and scenario.writes == 0


async def test_edited_draft_requires_fresh_review_digest(scenario):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        scenario.item.market_value = 2000
        old = {"decision": "confirm", "interrupt_id": review["interrupt_id"], "review_digest": review["review_digest"]}
        response = await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=old)
        assert response.status_code == 409 and scenario.writes == 0
        fresh = (await client.get("/chatbot/pending-action")).json()["pending_action"]
        assert fresh["items"][0]["market_value"] == 2000 and fresh["review_digest"] != review["review_digest"]
        response = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision", json={**old, "review_digest": fresh["review_digest"]}
        )
        assert response.status_code == 200 and scenario.writes == 1


@pytest.mark.parametrize("forged", ["interrupt", "digest", "no_pending"])
async def test_forged_or_missing_confirmation_is_rejected(scenario, forged):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = (
            await start_review(client)
            if forged != "no_pending"
            else {"interrupt_id": "fake", "review_digest": "0" * 64}
        )
        payload = {
            "decision": "confirm",
            "interrupt_id": review["interrupt_id"],
            "review_digest": review["review_digest"],
        }
        if forged == "interrupt":
            payload["interrupt_id"] = "fake"
        if forged == "digest":
            payload["review_digest"] = "0" * 64
        response = await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)
        assert response.status_code == 409 and scenario.writes == 0


async def test_parsing_tool_does_not_interrupt_or_apply(scenario):
    scenario.record.status = "PARSING"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        response = await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "同步持仓"}]})
        assert response.status_code == 200 and response.json()["pending_action"] is None
        assert "IMPORT_NOT_READY" in str(scenario.llm.calls[-1]) and scenario.writes == 0


async def test_later_turn_can_request_review_after_two_earlier_parsing_queries(scenario, monkeypatch):
    calls = []

    async def script(messages, *args, **kwargs):
        calls.append(messages)
        if len(calls) % 2:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_holding_import_confirmation",
                        "args": {"import_id": IMPORT_ID},
                        "id": f"request-{len(calls)}",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="仍在识别，请稍后查询。")

    monkeypatch.setattr(scenario.llm, "call", script)
    scenario.record.status = "PARSING"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.post(
                "/chatbot/chat", json={"messages": [{"role": "user", "content": "识别好了吗？"}]}
            )
            assert response.status_code == 200 and response.json()["pending_action"] is None
        scenario.record.status = "REVIEW_REQUIRED"
        response = await client.post(
            "/chatbot/chat", json={"messages": [{"role": "user", "content": "再查一次并让我确认"}]}
        )
        assert response.status_code == 200 and response.json()["pending_action"]["import_id"] == IMPORT_ID


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("case", ["valid", "invalid_image", "too_many", "wrong_account"])
async def test_upload_uses_existing_queue_and_server_session(scenario, monkeypatch, case):
    async def ensure_account(user_id, account_id):
        if user_id != 42 or account_id != 7:
            raise AccountNotFoundError("account_not_found")

    async def create_import(user_id, account_id, import_type, status, **kwargs):
        scenario.record = HoldingImport(
            id=IMPORT_ID, user_id=user_id, account_id=account_id, import_type=import_type, status=status, **kwargs
        )
        return scenario.record

    async def update_import(import_id, **kwargs):
        for name, value in kwargs.items():
            setattr(scenario.record, name, value)

    async def create_job(*args, **kwargs):
        return SimpleNamespace(id=9)

    async def enqueue(*args, **kwargs):
        scenario.enqueued.append(kwargs)

    monkeypatch.setattr(holding_module.portfolio_service, "ensure_account", ensure_account)
    monkeypatch.setattr(holding_module.import_repository, "create_import", create_import)
    monkeypatch.setattr(holding_module.import_repository, "update_import", update_import)
    monkeypatch.setattr(holding_module.job_repository, "create", create_job)
    monkeypatch.setattr(holding_module, "enqueue", enqueue)
    images = [b"not an image"] if case == "invalid_image" else [png_bytes()]
    if case == "too_many":
        images *= settings.HOLDING_IMPORT_MAX_IMAGES + 1
    account = 999 if case == "wrong_account" else 7
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        response = await client.post(
            f"/chatbot/holding-imports/screenshots?account_id={account}",
            files=[("files", ("holding.png", content, "image/png")) for content in images],
        )
        if case == "valid":
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "PARSING"
            assert scenario.record.chat_session_id == SESSION_ID and scenario.record.user_id == 42
            assert scenario.enqueued[0]["user_id"] == 42
            assert list(settings.HOLDING_IMPORT_TEMP_DIR.glob("*.png")) and scenario.writes == 0
        else:
            assert response.status_code == (404 if case == "wrong_account" else 422)
            assert scenario.enqueued == [] and not list(settings.HOLDING_IMPORT_TEMP_DIR.glob("*.png"))


def test_tools_expose_only_import_identifier():
    for tool in [get_holding_import, request_holding_import_confirmation]:
        assert tool in DEFAULT_AGENT_TOOLS and set(tool.args) == {"import_id"}


async def test_read_tool_uses_scoped_service_and_no_write(scenario):
    set_tool_runtime(ToolRuntimeContext(user_id=42, thread_id=SESSION_ID, request_id="fixture"))
    result = await get_holding_import.ainvoke({"import_id": IMPORT_ID})
    assert result.startswith("[TOOL_OK]") and "REVIEW_REQUIRED" in result and scenario.writes == 0
    set_tool_runtime(ToolRuntimeContext(user_id=42, thread_id="other", request_id="fixture"))
    assert (await get_holding_import.ainvoke({"import_id": IMPORT_ID})).startswith("[TOOL_ERROR] IMPORT_NOT_FOUND")
    with pytest.raises(ImportStateError, match="import_not_found"):
        await agent_holding_import_service.detail(42, "other", IMPORT_ID)


async def test_concurrent_decisions_do_not_resume_graph_twice(scenario, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    original = scenario.agent.resume_holding_import

    async def delayed_resume(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(scenario.agent, "resume_holding_import", delayed_resume)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        payload = {
            "decision": "confirm",
            "interrupt_id": review["interrupt_id"],
            "review_digest": review["review_digest"],
        }
        first = asyncio.create_task(client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload))
        await asyncio.wait_for(started.wait(), timeout=3)
        second = await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)
        release.set()
        assert second.status_code == 409 and (await first).status_code == 200
        assert scenario.writes == 1


async def test_applied_decision_can_retry_after_graph_resume_failure(scenario, monkeypatch):
    original = scenario.agent.resume_holding_import

    async def failed_resume(*args, **kwargs):
        raise RuntimeError("fixture failed LLM")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        payload = {
            "decision": "confirm",
            "interrupt_id": review["interrupt_id"],
            "review_digest": review["review_digest"],
        }
        monkeypatch.setattr(scenario.agent, "resume_holding_import", failed_resume)
        assert (await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)).status_code == 503
        assert scenario.writes == 1
        monkeypatch.setattr(scenario.agent, "resume_holding_import", original)
        assert (await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)).status_code == 200
        assert scenario.writes == 1
