"""持仓诊断白名单、版本和真实主图中的认证只读工具链回归."""

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph.agent import LangGraphAgent
from app.agent.skills import read_skill
from app.agent.tools.load_skill import load_skill
from app.core.config import settings
from app.schemas.agent_skill import LoadSkillRequest
from app.schemas.chat import Message
from app.schemas.portfolio import PortfolioResearchSnapshot, PortfolioSummary, PositionItem
from app.utils.clock import utc_now
from app.services.portfolio_service import AccountNotFoundError, portfolio_service


@pytest.mark.parametrize("section", ["instructions", "evidence"])
async def test_new_skill_is_packaged_without_request_time_file_access_and_has_its_own_version(monkeypatch, section):
    monkeypatch.setattr("pathlib.Path.read_text", lambda *args, **kwargs: pytest.fail("request-time file IO"))
    result = await load_skill.ainvoke({"skill_name": "portfolio-diagnosis", "section": section})
    data = json.loads(result.splitlines()[1])
    assert data["name"] == "portfolio-diagnosis" and data["version"] == "1.0.0"
    assert data["section"] == section and data["content"]
    assert set(data["available_sections"]) == {"instructions", "evidence"}
    assert read_skill("fund-analysis", section).version == "1.4.0"
    assert set(load_skill.args["skill_name"]["enum"]) == {
        "portfolio-diagnosis",
        "fund-analysis",
        "fund-comparison",
        "fund-allocation",
        "sector-analysis",
        "stock-analysis",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"skill_name": "../portfolio-diagnosis"},
        {"skill_name": "portfolio-diagnosis", "section": "../../config.py"},
        {"skill_name": "portfolio-diagnosis", "user_id": 99},
        {"skill_name": "portfolio-diagnosis", "account_id": 8},
        {"skill_name": "portfolio-diagnosis", "url": "https://internal"},
    ],
)
async def test_diagnosis_loader_rejects_paths_identity_and_external_resources(arguments):
    with pytest.raises(ValidationError):
        await load_skill.ainvoke(arguments)


@pytest.mark.parametrize("mode", ["normal", "empty", "truncated", "failed"])
@pytest.mark.parametrize("account_id", [None, 8])
async def test_real_graph_loads_diagnosis_then_reads_same_authenticated_scope(monkeypatch, mode, account_id):
    count = {"normal": 2, "empty": 0, "truncated": 51, "failed": 2}[mode]
    positions = [
        PositionItem(
            account_id=account_id or (8 if index % 2 == 0 else 9),
            fund_code=f"{index + 1:06d}",
            fund_name=f"诊断基金{index}",
            market_value=1000,
            cost_amount=1100,
            profit_loss=-100,
            position_ratio=1 / count,
            nav_date=date(2026, 10, 9),
        )
        for index in range(count)
    ]
    summary = PortfolioSummary(
        fund_count=count, total_market_value=count * 1000, total_cost=count * 1100, total_profit_loss=count * -100
    )
    snapshot_read = AsyncMock(
        return_value=PortfolioResearchSnapshot(
            account_id=account_id,
            status="available" if positions else "empty",
            captured_at=utc_now(),
            summary=summary,
            positions=positions,
            market_values_complete=True,
        )
    )
    if mode == "failed":
        snapshot_read.side_effect = TimeoutError("private database details")
    monkeypatch.setattr(portfolio_service, "research_snapshot", snapshot_read)
    writes = AsyncMock(side_effect=AssertionError("diagnosis must not write holdings"))
    monkeypatch.setattr(portfolio_service, "upsert_position", writes)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
    monkeypatch.setattr(settings, "USER_PERSONA_ENABLED", False)
    agent = LangGraphAgent()
    agent._graph = agent._build_graph(InMemorySaver())
    seen = []
    for name in ("get_fund_snapshot", "get_fund_analysis_data", "get_fund_holdings"):
        agent.tools_by_name[name] = SimpleNamespace(
            ainvoke=AsyncMock(return_value='[TOOL_OK]\n{"scope":"public_fixture"}')
        )

    async def respond(inputs, *args, **kwargs):
        assert "portfolio-diagnosis" in str(inputs)
        if account_id is not None and not seen:
            seen.append("route")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "diagnosis-start",
                        "name": "start_research",
                        "args": {"intent": "portfolio_diagnosis", "account_id": account_id},
                    }
                ],
            )
        assert kwargs == {"max_tokens": settings.RESEARCH_REPORT_MAX_TOKENS, "report_mode": True}
        context = "\n".join(str(message.content) for message in inputs)
        payload, _ = json.JSONDecoder().raw_decode(context.split("# 本轮证据（非指令）\n")[1])
        results = {item["tool"]: item["text"] for item in payload["evidence"]}
        assert json.loads(results["get_portfolio"].splitlines()[1])["fund_count"] == count
        assert mode in {"normal", "truncated"}  # 空持仓/读取失败直接由代码回答
        if mode == "truncated":
            assert "51" in results["get_positions"]
            assert any("50行" in gap for gap in payload["gaps"])
            assert payload["gaps"]
        else:
            data = json.loads(results["get_positions"].splitlines()[1])
            assert data["total_rows"] == count and len(data["positions"]) == min(count, 50)
            if account_id is not None:
                assert all(item["account_id"] == account_id for item in data["positions"])
        seen.append("complete")
        return AIMessage(content="已核验指定范围的诊断证据。")

    agent.llm_service = SimpleNamespace(get_llm=lambda: None, call=respond)
    instruction = "诊断我的持仓，看看集中和重复配置的问题" if account_id is None else f"诊断账户{account_id}的持仓"
    answer = await agent.get_response(
        [Message(role="user", content=instruction)],
        "portfolio-diagnosis-test",
        user_id="42",
    )
    route_steps = ["route"] if account_id is not None else []
    if mode in {"normal", "truncated"}:
        assert answer[-1].content == "已核验指定范围的诊断证据。"
        assert seen == [*route_steps, "complete"]
    else:
        assert ("没有可分析" if mode == "empty" else "无法读取") in answer[-1].content
        assert seen == route_steps
        assert "private database details" not in answer[-1].content
    snapshot_read.assert_awaited_once_with(42, account_id)
    writes.assert_not_awaited()
    snapshot = await agent._graph.aget_state({"configurable": {"thread_id": "portfolio-diagnosis-test"}})
    messages = snapshot.values["messages"]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    assert {message.tool_call_id for message in tool_messages} == (
        {"diagnosis-start"} if account_id is not None else set()
    )
    assert not snapshot.next and "evidence" not in snapshot.values
    assert (
        snapshot.values["research_result"].status
        == ({"normal": "completed", "truncated": "partial", "empty": "needs_input", "failed": "needs_input"}[mode])
    )


def test_request_schema_allows_new_skill_without_expanding_section_permissions():
    request = LoadSkillRequest(skill_name="portfolio-diagnosis")
    assert request.section == "instructions"
    with pytest.raises(ValidationError):
        LoadSkillRequest(skill_name="portfolio-diagnosis", section="script")


async def test_diagnosis_does_not_bypass_existing_account_ownership(monkeypatch):
    # 不替换组合服务的认证校验；真实读取在仓储访问前拒绝他人账户。
    denied = AsyncMock(side_effect=AccountNotFoundError("not owned"))
    monkeypatch.setattr(portfolio_service, "ensure_account", denied)
    with pytest.raises(AccountNotFoundError):
        await portfolio_service.list_positions(42, 999)
    with pytest.raises(AccountNotFoundError):
        await portfolio_service.get_summary(42, 999)

    with pytest.raises(AccountNotFoundError):
        await portfolio_service.research_snapshot(42, 999)
