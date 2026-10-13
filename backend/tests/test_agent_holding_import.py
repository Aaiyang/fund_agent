"""图片聊天导入：真实 LangGraph 中断、人工 HTTP 决策、隔离和上传验证."""

import asyncio
import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command
from PIL import Image

from app.agent.graph.agent import LangGraphAgent
from app.agent.tools.portfolio import get_holding_import, request_holding_import_confirmation, start_holding_import
from app.agent.tools.registry import DEFAULT_AGENT_TOOLS
from app.agent.tools.runtime import ToolRuntimeContext, set_tool_runtime
from app.api.v1 import chatbot
from app.api.v1.auth import get_current_session
from app.core.cache import InMemoryCacheService
from app.core.config import settings
from app.core.limiter import limiter
from app.integrations.holdings.base import DraftPositionItem, HoldingImportDraft
from app.models.holding_import import HoldingImport
from app.schemas.chat import Message
from app.schemas.graph import GraphState
from app.schemas.holding_import_graph import HoldingImportCall
from app.schemas.holding_import import ImportDetail, ImportItemOut
from app.services import holding_import_service as holding_module
from app.services import agent_holding_import_service as agent_import_module
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
            error_message=state.record.error_message,
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

    async def accounts(user_id):
        return [SimpleNamespace(id=7, name="支付宝"), SimpleNamespace(id=8, name="天天基金")] if user_id == 42 else []

    async def account(user_id, account_id):
        if user_id != 42 or account_id not in {7, 8}:
            raise AccountNotFoundError("account_not_found")
        return SimpleNamespace(id=account_id, name="支付宝" if account_id == 7 else "天天基金")

    @asynccontextmanager
    async def transaction():
        yield None

    async def update_import(import_id, **fields):
        for key, value in fields.items():
            setattr(state.record, key, value)

    async def enqueue(*args, **kwargs):
        state.enqueued.append(kwargs)

    monkeypatch.setattr(holding_module.portfolio_service, "list_accounts", accounts)
    monkeypatch.setattr(holding_module.portfolio_service, "ensure_account", account)
    monkeypatch.setattr(holding_module, "transaction_scope", transaction)
    monkeypatch.setattr(agent_import_module, "transaction_scope", transaction)
    monkeypatch.setattr(holding_module.import_repository, "update_import", update_import)
    monkeypatch.setattr(holding_module.job_repository, "create", AsyncMock(return_value=SimpleNamespace(id=9)))
    monkeypatch.setattr(holding_module, "enqueue", enqueue)

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


async def start_review(client, endpoint="chat", *, attached=False):
    response = await client.post(
        f"/chatbot/{endpoint}",
        json={
            "messages": [{"role": "user", "content": f"请同步截图里的持仓，批次 {IMPORT_ID}"}],
            "holding_import_ids": [IMPORT_ID] if attached else [],
        },
    )
    assert response.status_code == 200, response.text
    if endpoint == "chat/stream":
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["done"] is True
        return events[-1]["pending_action"]
    return response.json()["pending_action"]


def intent_then_final_llm(scenario, monkeypatch):
    async def final(messages, *args, **kwargs):
        scenario.llm.calls.append(messages)
        if len(scenario.llm.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "start_holding_import", "args": {}, "id": "import-intent", "type": "tool_call"}],
            )
        return AIMessage(content="已处理人工决策。")

    monkeypatch.setattr(scenario.llm, "call", final)


async def attach_images(client, instruction="请同步截图里的持仓", **fields):
    response = await client.post(
        "/chatbot/chat",
        json={
            "messages": [{"role": "user", "content": instruction}],
            "holding_import_ids": [IMPORT_ID],
            **fields,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["pending_action"]


async def advance_stage(client, pending, *, account_id=None):
    body = {"interrupt_id": pending["interrupt_id"]}
    step = "continue"
    if account_id is not None:
        step = "account"
        body["account_id"] = account_id
    return await client.post(f"/chatbot/holding-imports/{pending['import_id']}/{step}", json=body)


@pytest.mark.parametrize("instruction", ["我刚上传了 1 张图片。", "分析这个截图", "诊断我的持仓", "不要导入，只分析"])
async def test_attachment_without_import_tool_does_not_enter_subgraph(scenario, monkeypatch, instruction):
    scenario.record.status = "UPLOADED"

    async def ordinary_chat(messages, *args, **kwargs):
        scenario.llm.calls.append(messages)
        return AIMessage(content="请说明要分析图片还是导入持仓。")

    monkeypatch.setattr(scenario.llm, "call", ordinary_chat)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        assert await attach_images(client, instruction) is None
    assert scenario.record.status == "UPLOADED" and not scenario.enqueued and not scenario.writes
    assert len(scenario.llm.calls) == 1
    assert any(isinstance(m, HumanMessage) and m.content == instruction for m in scenario.llm.calls[0])
    assert any("不是导入授权" in str(m.content) for m in scenario.llm.calls[0])


@pytest.mark.parametrize("endpoint", ["chat", "chat/stream"])
async def test_import_intent_without_current_images_asks_upload(scenario, monkeypatch, endpoint):
    intent_then_final_llm(scenario, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        response = await client.post(
            f"/chatbot/{endpoint}", json={"messages": [{"role": "user", "content": "帮我导入持仓"}]}
        )
        assert response.status_code == 200, response.text
        if endpoint == "chat/stream":
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert "请先上传基金持仓截图" in "".join(event["content"] for event in events)
        else:
            assert "请先上传基金持仓截图" in response.text
        assert (await client.get("/chatbot/pending-action")).json()["pending_action"] is None
    assert len(scenario.llm.calls) == 1 and not scenario.enqueued and not scenario.writes
    snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}})
    results = [m for m in snapshot.values["messages"] if isinstance(m, ToolMessage)]
    assert len(results) == 1 and results[0].tool_call_id == "import-intent"


@pytest.mark.parametrize(
    "reason,code,notice",
    [
        ("not_holding_screenshot", "NOT_HOLDING_SCREENSHOT", "正确的持仓截图"),
        ("screenshot_unreadable", "SCREENSHOT_UNREADABLE", "清晰"),
        ("no_positions_detected", "NO_HOLDING_ROWS", "完整"),
        ("ocr_runtime_not_installed", "IMPORT_PARSE_FAILED", "暂时"),
    ],
)
async def test_recognition_content_failure_returns_actionable_notice(scenario, monkeypatch, reason, code, notice):
    intent_then_final_llm(scenario, monkeypatch)
    scenario.record.status = "UPLOADED"
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        pending = await attach_images(client)
        scenario.record.status = "PARSE_FAILED"
        scenario.record.error_message = reason
        response = await advance_stage(client, pending)
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
        assert notice in response.text
    snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}})
    assert any(isinstance(m, ToolMessage) and code in m.content for m in snapshot.values["messages"])
    assert len(scenario.llm.calls) == 1 and not scenario.writes and scenario.record.account_id is None


async def test_legacy_tool_cannot_start_historical_upload_without_current_attachment(scenario):
    scenario.record.status = "UPLOADED"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        response = await client.post(
            "/chatbot/chat", json={"messages": [{"role": "user", "content": "同步以前的图片"}]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None and "上传" in response.text
    assert scenario.record.status == "UPLOADED" and not scenario.enqueued and not scenario.writes


async def test_partial_recognition_errors_are_visible_in_review(scenario):
    scenario.record.error_message = "not_holding_screenshot"
    review = await agent_holding_import_service.review(42, SESSION_ID, IMPORT_ID)
    assert "部分图片" in review.notice and "正确的持仓截图" in review.notice


def test_import_intent_tool_is_registered_and_has_no_model_supplied_arguments():
    assert start_holding_import in DEFAULT_AGENT_TOOLS
    assert start_holding_import.args == {}


async def test_import_intent_and_other_tools_remain_paired_after_review(scenario, monkeypatch):
    async def script(messages, *args, **kwargs):
        scenario.llm.calls.append(messages)
        if len(scenario.llm.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "start_holding_import", "args": {}, "id": "intent"},
                    {"name": "get_positions", "args": {}, "id": "deferred-query"},
                ],
            )
        return AIMessage(content="已确认同步，现在可以分析持仓。")

    monkeypatch.setattr(scenario.llm, "call", script)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await attach_images(client, "导入截图到支付宝，再分析持仓")
        response = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": "confirm",
                "interrupt_id": review["interrupt_id"],
                "review_digest": review["review_digest"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
    messages = scenario.llm.calls[-1]
    call_ids = [call["id"] for m in messages if isinstance(m, AIMessage) for call in m.tool_calls]
    result_ids = [m.tool_call_id for m in messages if isinstance(m, ToolMessage)]
    assert sorted(call_ids) == sorted(result_ids) and len(result_ids) == len(set(result_ids)) == 3
    assert scenario.writes == 1


async def test_attachment_route_service_failure_returns_paired_notice(scenario, monkeypatch):
    intent_then_final_llm(scenario, monkeypatch)
    monkeypatch.setattr(agent_holding_import_service, "detail", AsyncMock(side_effect=RuntimeError("private_path")))
    result = await scenario.agent.get_response(
        [Message(role="user", content="导入截图持仓")], SESSION_ID, user_id="42", holding_import_ids=[IMPORT_ID]
    )
    assert "无法读取" in result[-1].content and "private_path" not in result[-1].content
    assert not scenario.writes and not scenario.enqueued and len(scenario.llm.calls) == 1
    snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}})
    tools = [m for m in snapshot.values["messages"] if isinstance(m, ToolMessage)]
    assert len(tools) == 1 and tools[0].tool_call_id == "import-intent"


async def test_manual_account_is_private_and_initial_parent_input_is_preserved(scenario):
    scenario.record.account_id = None
    instruction = "同步到支付宝或天天基金"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        pending = await attach_images(client, instruction)
        reply = await advance_stage(client, pending, account_id=8)
        assert reply.status_code == 200, reply.text
        review = reply.json()["pending_action"]
        assert review["account_id"] == 8
        snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}}, subgraphs=True)
        assert snapshot.values["holding_account_id"] is None
        assert snapshot.values["holding_instruction"] == instruction
        child = snapshot.tasks[0].state
        assert child.values["resolved_account_id"] == 8 and child.values["resolved_import_id"] == IMPORT_ID
        result = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": "confirm",
                "interrupt_id": review["interrupt_id"],
                "review_digest": review["review_digest"],
            },
        )
        assert result.status_code == 200, result.text
    finished = await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}})
    assert finished.values["holding_account_id"] is None and finished.values["holding_instruction"] == ""
    assert finished.values["holding_import_ids"] == [] and scenario.writes == 1


@pytest.mark.parametrize("reply", [{"import_id": "b" * 32, "action": "continue"}, "确认"])
async def test_processing_resume_for_other_batch_or_wrong_type_cannot_advance(scenario, reply):
    scenario.record.status = "UPLOADED"
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        pending = await attach_images(client)
        scenario.record.status = "REVIEW_REQUIRED"
        await scenario.agent._graph.ainvoke(
            Command(resume={pending["interrupt_id"]: reply}),
            config={"configurable": {"thread_id": SESSION_ID}, "metadata": {"user_id": "42"}},
        )
        still_pending = (await client.get("/chatbot/pending-action")).json()["pending_action"]
        assert still_pending["kind"] == "holding_import_processing"
        assert not scenario.writes and len(scenario.llm.calls) == 1
        recovered = await advance_stage(client, still_pending)
        assert recovered.status_code == 200
        assert recovered.json()["pending_action"]["kind"] == "holding_import_account"


@pytest.mark.parametrize(
    "reply",
    [
        {"import_id": IMPORT_ID, "account_id": True},
        {"import_id": IMPORT_ID, "account_id": "8"},
        {"import_id": "b" * 32, "account_id": 8},
    ],
)
async def test_invalid_or_other_batch_account_resume_keeps_selection_pending(scenario, reply):
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        pending = await attach_images(client)
        await scenario.agent._graph.ainvoke(
            Command(resume={pending["interrupt_id"]: reply}),
            config={"configurable": {"thread_id": SESSION_ID}, "metadata": {"user_id": "42"}},
        )
        current = (await client.get("/chatbot/pending-action")).json()["pending_action"]
        assert current["kind"] == "holding_import_account"
        assert scenario.record.account_id is None and not scenario.writes
        recovered = await advance_stage(client, current, account_id=8)
        assert recovered.status_code == 200 and recovered.json()["pending_action"]["account_id"] == 8


async def test_two_import_batches_do_not_inherit_first_manual_account(scenario, monkeypatch):
    scenario.record.account_id = None
    second_id = "b" * 32
    records = {IMPORT_ID: scenario.record, second_id: scenario.record.model_copy(update={"id": second_id})}

    async def get_import(user_id, import_id, **kwargs):
        return records.get(import_id) if user_id == 42 else None

    async def get_detail(user_id, import_id):
        record = await get_import(user_id, import_id)
        if record is None:
            return None
        return ImportDetail(
            id=record.id,
            account_id=record.account_id,
            import_type="SCREENSHOT",
            status=record.status,
            image_count=1,
            items_detected=1,
            items_confirmed=record.items_confirmed,
            items=[scenario.item],
        )

    async def confirm(user_id, import_id, *, expected_review_digest=None):
        detail = await get_detail(user_id, import_id)
        assert holding_review_digest(detail) == expected_review_digest
        scenario.writes += 1
        records[import_id].status = "APPLIED"
        records[import_id].items_confirmed = 1
        return {"applied": 1, "skipped": 0}

    monkeypatch.setattr(holding_module.import_repository, "get_import", get_import)
    monkeypatch.setattr(holding_module.holding_import_service, "get_import_detail", get_detail)
    monkeypatch.setattr(holding_module.holding_import_service, "confirm_import", confirm)
    intent_then_final_llm(scenario, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        response = await client.post(
            "/chatbot/chat",
            json={
                "messages": [{"role": "user", "content": "同步这些截图"}],
                "holding_import_ids": [IMPORT_ID, second_id],
            },
        )
        pending = response.json()["pending_action"]
        for import_id, account_id in [(IMPORT_ID, 8), (second_id, 7)]:
            assert pending["kind"] == "holding_import_account" and pending["import_id"] == import_id
            selected = await advance_stage(client, pending, account_id=account_id)
            assert selected.status_code == 200, selected.text
            review = selected.json()["pending_action"]
            assert review["account_id"] == account_id
            response = await client.post(
                f"/chatbot/holding-imports/{import_id}/decision",
                json={
                    "decision": "confirm",
                    "interrupt_id": review["interrupt_id"],
                    "review_digest": review["review_digest"],
                },
            )
            assert response.status_code == 200, response.text
            pending = response.json()["pending_action"]
    assert pending is None and scenario.writes == 2
    assert records[IMPORT_ID].account_id == 8 and records[second_id].account_id == 7


async def test_attachment_waits_for_recognition_account_and_human_confirmation(scenario, monkeypatch):
    intent_then_final_llm(scenario, monkeypatch)
    scenario.record.status = "UPLOADED"
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        processing = await attach_images(client)
        assert processing["kind"] == "holding_import_processing"
        assert scenario.record.status == "PARSING"
        assert len(scenario.enqueued) == len(scenario.llm.calls) == 1 and not scenario.writes
        assert (await advance_stage(client, processing)).status_code == 409
        assert (
            await client.post(
                f"/chatbot/holding-imports/{IMPORT_ID}/decision",
                json={
                    "decision": "confirm",
                    "interrupt_id": processing["interrupt_id"],
                },
            )
        ).status_code == 409
        assert (
            await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "确认"}]})
        ).status_code == 409
        scenario.record.status = "REVIEW_REQUIRED"
        response = await advance_stage(client, processing)
        assert response.status_code == 200, response.text
        selection = response.json()["pending_action"]
        assert selection["kind"] == "holding_import_account"
        assert {account["id"] for account in selection["accounts"]} == {7, 8}
        assert (await advance_stage(client, processing)).status_code == 409
        assert (await advance_stage(client, selection, account_id=999)).status_code == 404
        response = await advance_stage(client, selection, account_id=7)
        assert response.status_code == 200, response.text
        review = response.json()["pending_action"]
        assert review["kind"] == "holding_import_review" and review["account_name"] == "支付宝"
        assert scenario.record.account_id == 7 and len(scenario.llm.calls) == 1 and not scenario.writes
        assert (await advance_stage(client, selection, account_id=8)).status_code == 409
        payload = {
            "decision": "confirm",
            "interrupt_id": review["interrupt_id"],
            "review_digest": review["review_digest"],
        }
        response = await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
        assert scenario.record.status == "APPLIED" and scenario.writes == 1
        assert len(scenario.llm.calls) == 2 and len(scenario.enqueued) == 1
        assert (await client.post(f"/chatbot/holding-imports/{IMPORT_ID}/decision", json=payload)).status_code == 200
        assert scenario.writes == 1


@pytest.mark.parametrize(
    "instruction,fields,expected",
    [
        ("把截图同步到天天基金账户", {}, 8),
        ("支付宝账户导入这个截图", {}, 7),
        ("把支付宝的截图导入到天天基金账户", {}, 8),
        ("请同步截图持仓", {"holding_account_id": 8}, 8),
    ],
)
async def test_initial_explicit_account_skips_question(scenario, monkeypatch, instruction, fields, expected):
    intent_then_final_llm(scenario, monkeypatch)
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await attach_images(client, instruction, **fields)
        assert review["kind"] == "holding_import_review" and review["account_id"] == expected
        assert scenario.record.account_id == expected and len(scenario.llm.calls) == 1 and not scenario.writes


@pytest.mark.parametrize(
    "instruction",
    [
        "请同步截图",
        "同步到支付宝或天天基金",
        "同步到支付宝但不要导入这个账户",
        "同步持仓，分析一下支付宝",
    ],
)
async def test_unspecified_ambiguous_or_negated_account_always_asks(scenario, instruction):
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        selection = await attach_images(client, instruction)
        assert selection["kind"] == "holding_import_account"
        assert scenario.record.account_id is None and len(scenario.llm.calls) == 1 and not scenario.writes


@pytest.mark.parametrize("endpoint", ["chat", "chat/stream"])
async def test_account_can_be_supplied_in_chat_but_confirmation_cannot(scenario, endpoint):
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        selection = await attach_images(client)
        key = chatbot.cache_key("agent:holding-decision", SESSION_ID)
        assert await chatbot.cache_service.acquire_lock(key)
        answer = {"messages": [{"role": "user", "content": "天天基金"}]}
        assert (await client.post(f"/chatbot/{endpoint}", json=answer)).status_code == 409
        await chatbot.cache_service.release_lock(key)
        response = await client.post(f"/chatbot/{endpoint}", json=answer)
        assert response.status_code == 200, response.text
        review = (await client.get("/chatbot/pending-action")).json()["pending_action"]
        assert review["kind"] == "holding_import_review" and review["account_id"] == 8
        assert review["interrupt_id"] != selection["interrupt_id"]
        assert not scenario.writes and len(scenario.llm.calls) == 1
        assert (
            await client.post(f"/chatbot/{endpoint}", json={"messages": [{"role": "user", "content": "确认"}]})
        ).status_code == 409


@pytest.mark.parametrize("status", ["UPLOADED", "REVIEW_REQUIRED"])
async def test_processing_and_account_interrupt_recover_after_reconnect(scenario, monkeypatch, status):
    scenario.record.status = status
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        original = await attach_images(client)
        recovered = LangGraphAgent()
        recovered._graph = recovered._build_graph(scenario.saver)
        monkeypatch.setattr(recovered, "llm_service", scenario.llm)
        monkeypatch.setattr(chatbot, "agent", recovered)
        assert (await client.get("/chatbot/pending-action")).json()["pending_action"] == original
        if status == "UPLOADED":
            scenario.record.status = "REVIEW_REQUIRED"
            response = await advance_stage(client, original)
            assert response.status_code == 200, response.text
            assert response.json()["pending_action"]["kind"] == "holding_import_account"
            assert len(scenario.enqueued) == 1
        assert len(scenario.llm.calls) == 1


@pytest.mark.parametrize("status", ["UPLOADED", "REVIEW_REQUIRED"])
async def test_cancel_before_review_never_applies(scenario, monkeypatch, status):
    intent_then_final_llm(scenario, monkeypatch)
    scenario.record.status = status
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        pending = await attach_images(client)
        response = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": "cancel",
                "interrupt_id": pending["interrupt_id"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
        assert scenario.record.status == "CANCELLED" and scenario.cancels == 1 and not scenario.writes
        assert len(scenario.llm.calls) == 2


@pytest.mark.parametrize("status", ["UPLOADED", "REVIEW_REQUIRED"])
async def test_pending_stage_does_not_leak_to_other_user(scenario, status):
    scenario.record.status = status
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        pending = await attach_images(client)
        scenario.identity.user_id = 99
        assert (await client.get("/chatbot/pending-action")).status_code == 404
        response = await advance_stage(client, pending, account_id=7 if status == "REVIEW_REQUIRED" else None)
        assert response.status_code == 404
        assert not scenario.writes


@pytest.mark.parametrize("failed", [False, True])
async def test_late_worker_result_does_not_resurrect_cancelled_draft(scenario, monkeypatch, failed):
    scenario.record.status = "PARSING"
    scenario.record.account_id = None

    async def parse(self, payload):
        assert payload.account_id is None
        scenario.record.status = "CANCELLED"
        if failed:
            raise RuntimeError("cancelled_during_ocr")
        return HoldingImportDraft(items=[DraftPositionItem(matched_fund_code="005827", market_value=1000)])

    monkeypatch.setattr(holding_module.ScreenshotImportProvider, "parse", parse)
    monkeypatch.setattr(holding_module.holding_import_service, "_existing_image_paths", lambda import_id: [])
    replace = AsyncMock()
    monkeypatch.setattr(holding_module.import_repository, "replace_items", replace)
    await holding_module.holding_import_service.process_screenshot_import(IMPORT_ID, 42)
    assert scenario.record.status == "CANCELLED"
    replace.assert_not_awaited()


async def test_attached_stream_yields_processing_without_polling_llm(scenario):
    scenario.record.status = "UPLOADED"
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        processing = await start_review(client, "chat/stream", attached=True)
        assert processing["kind"] == "holding_import_processing"
        assert len(scenario.enqueued) == len(scenario.llm.calls) == 1


async def test_recognition_failure_releases_main_graph_without_import(scenario, monkeypatch):
    intent_then_final_llm(scenario, monkeypatch)
    scenario.record.status = "UPLOADED"
    scenario.record.account_id = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        processing = await attach_images(client)
        scenario.record.status = "PARSE_FAILED"
        response = await advance_stage(client, processing)
        assert response.status_code == 200, response.text
        assert response.json()["pending_action"] is None
        assert not scenario.writes and len(scenario.llm.calls) == 1
        messages = (await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}})).values[
            "messages"
        ]
        assert any(
            isinstance(message, ToolMessage) and "IMPORT_PARSE_FAILED" in message.content for message in messages
        )


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


async def test_parsing_tool_waits_in_subgraph_without_applying(scenario):
    scenario.record.status = "PARSING"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        response = await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "同步持仓"}]})
        assert response.status_code == 200 and response.json()["pending_action"]["kind"] == "holding_import_processing"
        assert len(scenario.llm.calls) == 1 and scenario.writes == 0


async def test_later_turn_can_request_review_after_two_earlier_parsing_queries(scenario, monkeypatch):
    calls = []

    async def script(messages, *args, **kwargs):
        calls.append(messages)
        if len(calls) % 2:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_holding_import"
                        if scenario.record.status == "PARSING"
                        else "request_holding_import_confirmation",
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


@pytest.mark.parametrize("case", ["valid", "unassigned", "invalid_image", "too_many", "wrong_account"])
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
            "/chatbot/holding-imports/screenshots"
            if case == "unassigned"
            else f"/chatbot/holding-imports/screenshots?account_id={account}",
            files=[("files", ("holding.png", content, "image/png")) for content in images],
        )
        if case in {"valid", "unassigned"}:
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "UPLOADED"
            assert scenario.record.chat_session_id == SESSION_ID and scenario.record.user_id == 42
            assert scenario.enqueued == []
            if case == "unassigned":
                assert scenario.record.account_id is None
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


async def test_review_pauses_in_checkpointed_child_node(scenario):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
    snapshot = await scenario.agent._graph.aget_state({"configurable": {"thread_id": SESSION_ID}}, subgraphs=True)
    assert snapshot.next == ("holding_import",)
    child = snapshot.tasks[0].state
    assert child.next == ("human_review",)
    assert HoldingImportCall.model_validate(child.values["active_call"]).call_id == "image-review"
    assert "active_call" not in snapshot.values and "review" not in snapshot.values
    assert child.tasks[0].interrupts[0].id == review["interrupt_id"]
    assert len(scenario.llm.calls) == 1 and scenario.writes == 0


@pytest.mark.parametrize("decision", ["confirm", "cancel"])
async def test_mixed_tool_batch_is_not_reexecuted_after_human_resume(scenario, monkeypatch, decision):
    executions = []

    async def echo(query: str) -> str:
        executions.append(query)
        return "查询完成"

    scenario.agent.tools_by_name["echo"] = StructuredTool.from_function(
        coroutine=echo, name="echo", description="test query"
    )

    async def script(messages, *args, **kwargs):
        scenario.llm.calls.append(messages)
        if len(scenario.llm.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "echo", "args": {"query": "行情"}, "id": "other-call"},
                    {
                        "name": "request_holding_import_confirmation",
                        "args": {"import_id": IMPORT_ID},
                        "id": "review-call",
                    },
                ],
            )
        return AIMessage(content="复核处理完成")

    monkeypatch.setattr(scenario.llm, "call", script)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        assert executions == ["行情"] and scenario.writes == 0
        reply = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": decision,
                "interrupt_id": review["interrupt_id"],
                "review_digest": review["review_digest"],
            },
        )
        assert reply.status_code == 200, reply.text
        assert executions == ["行情"] and len(scenario.llm.calls) == 2
    results = [m for m in scenario.llm.calls[-1] if isinstance(m, ToolMessage)]
    assert {m.tool_call_id for m in results} == {"other-call", "review-call"}
    assert len(results) == 2


@pytest.mark.parametrize(
    "resume_value",
    ["确认", {"decision": "confirm", "import_id": IMPORT_ID}, {"decision": ["confirm"], "import_id": IMPORT_ID}],
)
async def test_direct_resume_does_not_apply_and_keeps_review_pending(scenario, resume_value):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
    await scenario.agent._graph.ainvoke(
        Command(resume={review["interrupt_id"]: resume_value}),
        {"configurable": {"thread_id": SESSION_ID}, "metadata": {"user_id": "42"}},
    )
    assert await scenario.agent.get_pending_holding_review(SESSION_ID) is not None
    assert scenario.writes == 0 and scenario.record.status == "REVIEW_REQUIRED"
    assert len(scenario.llm.calls) == 1


@pytest.mark.parametrize("args", [{"import_id": "invalid"}, {"import_id": IMPORT_ID, "user_id": 99}])
async def test_subgraph_rejects_invalid_or_identity_bearing_tool_args(scenario, monkeypatch, args):
    async def script(messages, *unused, **kwargs):
        scenario.llm.calls.append(messages)
        if len(scenario.llm.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "request_holding_import_confirmation", "args": args, "id": "bad-call"}],
            )
        return AIMessage(content="批次参数无效")

    monkeypatch.setattr(scenario.llm, "call", script)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        reply = await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "同步截图"}]})
    assert reply.status_code == 200 and reply.json()["pending_action"] is None
    assert "INVALID_ARGUMENT" in str(scenario.llm.calls[-1]) and scenario.writes == 0


async def test_read_only_import_query_routes_through_child_without_interrupt(scenario, monkeypatch):
    async def script(messages, *args, **kwargs):
        scenario.llm.calls.append(messages)
        if len(scenario.llm.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "get_holding_import", "args": {"import_id": IMPORT_ID}, "id": "read-call"}],
            )
        return AIMessage(content="草稿已识别，尚未应用")

    monkeypatch.setattr(scenario.llm, "call", script)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        reply = await client.post("/chatbot/chat", json={"messages": [{"role": "user", "content": "查截图进度"}]})
    assert reply.status_code == 200 and reply.json()["pending_action"] is None
    assert "REVIEW_REQUIRED" in str(scenario.llm.calls[-1])
    assert len(scenario.llm.calls) == 2 and scenario.writes == 0
    assert "holding_import" in scenario.agent._graph.get_graph().nodes


async def test_deployment_can_resume_previous_tool_node_checkpoint(scenario, monkeypatch):
    # Simulate the previous topology: the interrupt lived inside tool_call.
    async def legacy_chat(state, config):
        result = await scenario.agent._chat(state, config)
        return Command(update=result.update, goto="tool_call" if result.goto == "holding_import" else result.goto)

    legacy = StateGraph(GraphState)
    legacy.add_node("chat", legacy_chat, destinations=("tool_call", END))
    legacy.add_node("tool_call", scenario.agent._tool_call, destinations=("chat",))
    legacy.set_entry_point("chat")
    scenario.agent._graph = legacy.compile(checkpointer=scenario.saver)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        recovered = LangGraphAgent()
        recovered._graph = recovered._build_graph(scenario.saver)
        monkeypatch.setattr(recovered, "llm_service", scenario.llm)
        monkeypatch.setattr(chatbot, "agent", recovered)
        reply = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": "confirm",
                "interrupt_id": review["interrupt_id"],
                "review_digest": review["review_digest"],
            },
        )
    assert reply.status_code == 200, reply.text
    assert scenario.writes == 1 and reply.json()["pending_action"] is None
    assert len(scenario.llm.calls) == 2


@pytest.mark.parametrize("duplicate", [False, True])
@pytest.mark.parametrize("attached", [False, True])
async def test_multiple_import_calls_are_reviewed_sequentially_and_apply_once(
    scenario, monkeypatch, duplicate, attached
):
    second_id = IMPORT_ID if duplicate else "b" * 32
    records = {IMPORT_ID: scenario.record}
    if not duplicate:
        records[second_id] = scenario.record.model_copy(update={"id": second_id})

    async def get_import(user_id, import_id, **kwargs):
        return records.get(import_id) if user_id == 42 else None

    async def get_detail(user_id, import_id):
        record = await get_import(user_id, import_id)
        if record is None:
            return None
        return ImportDetail(
            id=record.id,
            account_id=7,
            import_type="SCREENSHOT",
            status=record.status,
            image_count=1,
            items_detected=1,
            items_confirmed=record.items_confirmed,
            items=[scenario.item],
        )

    async def confirm(user_id, import_id, *, expected_review_digest=None):
        detail = await get_detail(user_id, import_id)
        record = records[import_id]
        if record.status == "APPLIED":
            return {"applied": 1, "skipped": 0}
        if expected_review_digest != holding_review_digest(detail):
            raise ImportStateError("import_review_changed")
        scenario.writes += 1
        record.status = "APPLIED"
        record.items_confirmed = 1
        return {"applied": 1, "skipped": 0}

    async def script(messages, *args, **kwargs):
        scenario.llm.calls.append(messages)
        if len(scenario.llm.calls) == 1:
            if attached:
                return AIMessage(
                    content="", tool_calls=[{"name": "start_holding_import", "args": {}, "id": "import-intent"}]
                )
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_holding_import_confirmation",
                        "args": {"import_id": import_id},
                        "id": f"review-{i}",
                    }
                    for i, import_id in enumerate([IMPORT_ID, second_id])
                ],
            )
        return AIMessage(content="导入完成")

    monkeypatch.setattr(holding_module.import_repository, "get_import", get_import)
    monkeypatch.setattr(holding_module.holding_import_service, "get_import_detail", get_detail)
    monkeypatch.setattr(holding_module.holding_import_service, "confirm_import", confirm)
    monkeypatch.setattr(scenario.llm, "call", script)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        if attached:
            reply = await client.post(
                "/chatbot/chat",
                json={
                    "messages": [{"role": "user", "content": "同步截图"}],
                    "holding_import_ids": list(dict.fromkeys([IMPORT_ID, second_id])),
                },
            )
            assert reply.status_code == 200, reply.text
            review = reply.json()["pending_action"]
            assert len(scenario.llm.calls) == 1
        else:
            review = await start_review(client)
        count = 1 if duplicate else 2
        for expected_id in list(dict.fromkeys([IMPORT_ID, second_id])):
            assert review["import_id"] == expected_id
            reply = await client.post(
                f"/chatbot/holding-imports/{expected_id}/decision",
                json={
                    "decision": "confirm",
                    "interrupt_id": review["interrupt_id"],
                    "review_digest": review["review_digest"],
                },
            )
            assert reply.status_code == 200, reply.text
            review = reply.json()["pending_action"]
        assert review is None and scenario.writes == count
        assert len(scenario.llm.calls) == 2
        results = [m for m in scenario.llm.calls[-1] if isinstance(m, ToolMessage)]
        if attached:
            assert len(results) == count + 1 and len({m.tool_call_id for m in results}) == count + 1
        else:
            assert {m.tool_call_id for m in results} == {"review-0", "review-1"}
            assert len(results) == 2


async def test_subgraph_query_failure_returns_paired_safe_tool_error(scenario, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("private fixture database error")

    monkeypatch.setattr(agent_holding_import_service, "detail", unavailable)
    # No attachment: let the graph, rather than the HTTP pre-validation, encounter the failure.
    result = await scenario.agent.get_response(
        [Message(role="user", content="查询图片复核")], SESSION_ID, user_id="42"
    )
    assert result[-1].role == "assistant"
    assert len(scenario.llm.calls) == 2 and scenario.writes == 0
    tools = [m for m in scenario.llm.calls[-1] if isinstance(m, ToolMessage)]
    assert len(tools) == 1 and tools[0].tool_call_id == "image-review"
    assert "UPSTREAM_ERROR" in tools[0].content and "private fixture" not in tools[0].content


async def test_memory_is_refreshed_after_review_without_shared_resume_updates(scenario, monkeypatch):
    memory = SimpleNamespace(
        search=AsyncMock(side_effect=["旧记忆", "更新后的记忆"]), add=AsyncMock(return_value="queued")
    )
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", True)
    monkeypatch.setattr("app.agent.graph.agent.memory_service", memory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scenario.app), base_url="http://test") as client:
        review = await start_review(client)
        reply = await client.post(
            f"/chatbot/holding-imports/{IMPORT_ID}/decision",
            json={
                "decision": "confirm",
                "interrupt_id": review["interrupt_id"],
                "review_digest": review["review_digest"],
            },
        )
    assert reply.status_code == 200, reply.text
    assert memory.search.await_count == 2 and memory.add.await_count == 1
    assert "更新后的记忆" in str(scenario.llm.calls[-1])
    assert len(scenario.llm.calls) == 2 and scenario.writes == 1
