"""输出契约由 schema 生成，提示词必须真的带上它.

这一层的存在理由都是实测故障：提示词手写"120字"而 schema 允许 700；`ReviewIssue.role`
的合法英文值从未出现在提示词里，模型漏字段 → 交叉审核整节点被判未完成；会话标题模板
的 {user_message} 占位符从来没被替换过。
"""

import hashlib

import pytest
from pydantic import BaseModel

from app.agent.prompts import (
    SYSTEM_PROMPT_VERSION,
    _GRAPH_PROMPT_KEYS,
    load_session_title_prompt,
    load_system_prompt,
)
from app.agent.prompts.contract import AGENT_ANALYSIS_CONTRACT, RESEARCH_REVIEW_CONTRACT, describe_schema
from app.agent.prompts.graph import role_prompt, review_prompt
from app.schemas.multi_role_research import AgentAnalysis, ResearchReview


def _field_names(model: type[BaseModel]) -> set[str]:
    """嵌套一层的字段名集合，用于"schema 改了提示词必须跟着变"的守卫."""
    names = set(model.model_fields)
    for field in model.model_fields.values():
        for arg in getattr(field.annotation, "__args__", ()) or ():
            names |= set(getattr(arg, "model_fields", {}))
    return names


def test_contract_lists_every_schema_field_and_its_enum_tokens():
    for model, text in ((AgentAnalysis, AGENT_ANALYSIS_CONTRACT), (ResearchReview, RESEARCH_REVIEW_CONTRACT)):
        for name in _field_names(model):
            assert f"- {name}（" in text, f"{model.__name__}.{name} 没进契约"
    assert "fact | inference | conditional" in AGENT_ANALYSIS_CONTRACT
    assert "completed | blocked" in AGENT_ANALYSIS_CONTRACT
    assert "fundamentals | risk | portfolio" in RESEARCH_REVIEW_CONTRACT
    assert "最多 8" in AGENT_ANALYSIS_CONTRACT  # coverage 上限与 assignment 数量同量级


def test_describe_schema_rejects_an_empty_model():
    with pytest.raises(ValueError, match="no fields"):
        describe_schema(BaseModel)


def test_role_and_review_prompts_carry_the_contract_and_only_their_own_rules():
    first = role_prompt("risk", revision=False)
    # addressed_issue_indices 本来就在契约里；修订轮要区分的是那句规则本身。
    assert "风险分析员" in first and "本轮收到审核反馈" not in first
    assert "addressed_issue_indices" in first
    assert "本轮收到审核反馈" in role_prompt("risk", revision=True)
    assert "- role（必填，只能是 fundamentals | risk | portfolio）" in review_prompt()
    assert "风险分析员" not in review_prompt()


def test_unknown_role_fails_loudly_instead_of_dropping_its_brief():
    with pytest.raises(KeyError):
        role_prompt("momentum", revision=False)


def test_session_title_prompt_fills_its_placeholder():
    rendered = load_session_title_prompt("帮我分析011452")
    assert "{user_message}" not in rendered and "帮我分析011452" in rendered


def test_prompt_version_covers_the_inline_prompts():
    """内联提示词或 schema 契约一改，KV 前缀指纹必须跟着变（以前只有 system.md 记账）."""
    digest = hashlib.sha256(repr(_GRAPH_PROMPT_KEYS).encode()).hexdigest()[:8]
    assert SYSTEM_PROMPT_VERSION.endswith(digest)
    assert "fund-chart v2" in load_system_prompt(username="yyy", long_term_memory="")
    assert "{user_message}" not in load_system_prompt(long_term_memory="")
