"""研究任务的父子图契约；证据和中间推理仅属于研究子图."""

from datetime import datetime
from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.fund_selection import FundSelectionOption
from app.schemas.agent_skill import SkillName
from app.schemas.multi_role_research import AgentReport, ResearchAssignment, ResearchReview, ResearchRole

ResearchIntent = Literal[
    "fund_research",
    "fund_comparison",
    "portfolio_diagnosis",
    "allocation_analysis",
    "sector_research",
    "stock_research",
]
AllocationAction = Literal["build", "increase", "reduce", "exit", "compare"]


class ResearchRequest(BaseModel):
    """只读研究请求；名称先解析，不接受模型指定的认证身份或交易授权."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intent: ResearchIntent
    mode: Literal["standard", "deep"] = "standard"
    strategy: Literal["single", "multi_role"] = "single"
    fund_queries: list[str] = Field(default_factory=list, max_length=3)
    account_id: int | None = Field(default=None, ge=1, strict=True)
    action: AllocationAction | None = None
    proposed_amount: float | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False, strict=True)
    sector_query: str | None = Field(default=None, min_length=1, max_length=64)
    stock_symbol: str | None = Field(default=None, pattern=r"^(?:(?:sh|sz|bj)\d{6}|hk\d{5}|us[A-Z][A-Z.]{0,10})$")

    @field_validator("fund_queries")
    @classmethod
    def valid_queries(cls, values: list[str]) -> list[str]:
        """有界、去重名称输入，不从工具正文或旧摘要补造目标."""
        cleaned = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 120 for value in cleaned):
            raise ValueError("基金查询词须为1–120字")
        return cleaned

    @model_validator(mode="after")
    def valid_scope(self) -> "ResearchRequest":
        """单基金研究和操作分析必须指定对象，组合诊断可自动取重点基金."""
        if self.strategy == "multi_role" and self.intent in {"sector_research", "stock_research"}:
            raise ValueError("多角色研究暂支持基金、基金对比、持仓诊断和配置分析")
        if self.intent in {"fund_research", "allocation_analysis"} and not self.fund_queries:
            raise ValueError("请先提供要研究的基金名称或六位代码")
        if self.intent == "fund_comparison" and len(self.fund_queries) < 2:
            raise ValueError("基金对比需要两到三只不同的基金名称或代码")
        if self.intent == "sector_research" and not self.sector_query:
            raise ValueError("请提供板块名称或真实BK代码")
        if self.intent == "stock_research" and not self.stock_symbol:
            raise ValueError("请提供带市场前缀的股票代码，不猜市场或公司")
        if self.intent != "sector_research" and self.sector_query is not None:
            raise ValueError("板块查询词只适用于板块研究")
        if self.intent != "stock_research" and self.stock_symbol is not None:
            raise ValueError("股票代码只适用于股票研究")
        if self.intent in {"sector_research", "stock_research"} and self.fund_queries:
            raise ValueError("基金与股票板块研究需分别处理")
        if self.intent != "allocation_analysis" and (self.action or self.proposed_amount is not None):
            raise ValueError("操作和金额只适用于操作方案分析")
        if self.intent == "allocation_analysis" and self.action is None:
            self.action = "compare"
        if self.proposed_amount is not None and len(self.fund_queries) != 1:
            raise ValueError("金额情景一次只能针对一只基金")
        return self


class ResearchTask(BaseModel):
    """父图只保存请求、已解析对象和轮次；人工恢复沿用同一任务."""

    turn_id: str
    request: ResearchRequest
    instruction: str
    resolved_funds: list[FundSelectionOption] = Field(default_factory=list)
    source_research_id: str | None = None
    # 授权来源：model 需要 route_task 逐项取证，followup/client 由服务端直接放行。
    requested_by: Literal["model", "followup", "client"] = "model"


class ResearchResult(BaseModel):
    """子图回传的紧凑结果，完整回答只保存在消息中."""

    turn_id: str
    intent: ResearchIntent
    status: Literal["completed", "partial", "needs_input"]
    fund_codes: list[str] = Field(default_factory=list)
    evidence_tools: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    strategy: Literal["single", "multi_role"] = "single"


class ResearchEvidence(BaseModel):
    """复用现有工具结果，保留日期与警告；失败和截断必须公开."""

    tool: str
    args: dict = Field(default_factory=dict)
    success: bool
    text: str
    data: dict | list | str | None = None


class ResearchToolCall(BaseModel):
    """代码生成并校验的有界只读计划，不允许任意工具扩展."""

    name: str
    args: dict = Field(default_factory=dict)


class ResearchGraphState(BaseModel):
    """消息及最终结果是共享通道，取证载荷和情景计算是私有通道."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    turn_id: str = ""
    long_term_memory: str = ""
    memory_write_status: str | None = None
    research_task: ResearchTask | None = None
    research_result: ResearchResult | None = None
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    fund_codes: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    scenario: dict = Field(default_factory=dict)
    clarification: str | None = None
    portfolio_snapshot: dict = Field(default_factory=dict)
    skill_name: SkillName | None = None
    skill_instructions: str = ""
    skill_evidence: str = ""
    tool_plan: list[ResearchToolCall] = Field(default_factory=list)
    agent_reports: list[AgentReport] = Field(default_factory=list)
    agent_review: ResearchReview | None = None
    agent_assignments: list[ResearchAssignment] = Field(default_factory=list)
    agent_evidence_packet: list[dict] = Field(default_factory=list)
    agent_initial_evidence_ids: list[str] = Field(default_factory=list)
    agent_revision_roles: list[ResearchRole] = Field(default_factory=list)
    agent_review_status: Literal["completed", "partial", "failed"] | None = None
    agent_started_at: datetime | None = None
