"""Bounded, task-scoped communication between research agents."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


# 角色按专业基金评价维度切分，每个角色绑定一块真实可取的数据。
# 费率、同类排名/百分位、换手率、全部持仓在系统里没有数据来源，所以不设角色——
# 让角色去分析拿不到的数据，产出只能是套话。
ResearchRole = Literal["performance", "risk", "holdings", "manager", "disclosure", "portfolio"]
ResearchStage = Literal["evidence", "analysis", "review", "supplement", "revision", "report"]
GapText = Annotated[str, Field(min_length=1, max_length=500)]
EvidenceId = Annotated[str, Field(min_length=1, max_length=64)]
TaskId = Annotated[str, Field(min_length=1, max_length=100)]


class EvidenceRequirement(BaseModel):
    """一条证据要求：命中 tools 里任一工具即算，scope 决定是否每只对象都要有."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str = Field(min_length=1, max_length=60)
    tools: list[str] = Field(min_length=1)
    scope: Literal["per_fund", "global"] = "global"


class ResearchAssignment(BaseModel):
    """Server-owned completion criteria: one per role, never per fund × role.

    任务数随基金数量膨胀时，输出上限就成了硬约束——三只基金对比曾让一个角色拿到
    4 条任务、13 个必需工具组，而 findings 上限只有 4，契约在数学上就无法满足。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: TaskId
    role: ResearchRole
    summary: str = Field(min_length=1, max_length=400)
    required_evidence: list[EvidenceRequirement] = Field(default_factory=list, max_length=6)


class TaskCoverage(BaseModel):
    """服务端从存活发现的引用推导出的覆盖结论；这张表不由模型填写.

    模型擅长引用、不擅长记账：让它自己填覆盖表并做索引交叉核对，实测 31 次角色
    输出 0 次 completed。改成代码从它实际引用的证据反推，覆盖数字才可核。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: TaskId
    status: Literal["completed", "partial", "blocked"]
    met: list[str] = Field(default_factory=list, max_length=6)
    missing: list[str] = Field(default_factory=list, max_length=6)
    explanation: str = Field(default="", max_length=300)
    # 该角色有多少条结论因引用无法核对而被整条丢弃。交给成文节点如实说明，
    # 而不是让它从缺口文字里猜。
    dropped_citations: int = Field(default=0, ge=0)


class EvidenceFinding(BaseModel):
    """A claim references server-issued evidence IDs, never another agent's prose."""

    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1, max_length=700)
    kind: Literal["fact", "inference", "conditional"]
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=6)
    limitation: str = Field(max_length=500)


class DimensionStance(BaseModel):
    """本维度对某个决策议题的专业立场：一个可以被同事的证据翻盘的判断.

    立场不是覆盖声明——它永不参与状态判定，只用于成文署名与跨维度对立配对。
    ``topic`` 用枚举而不是自由文本，因为"同一议题上方向相反"要能由代码配出来；
    自由文本的对象名基本配不中。
    """

    model_config = ConfigDict(extra="forbid")
    verdict: str = Field(min_length=1, max_length=120)
    marker: Literal["support", "oppose", "conditional", "neutral"] = "neutral"
    topic: Literal[
        "short_term_holding",
        "long_term_holding",
        "position_size",
        "entry_timing",
        "benchmark_fit",
        "risk_budget",
        "information_quality",
        "team_stability",
        "other",
    ] = "other"
    # 立场在什么条件下翻转；marker=neutral 时它就是"证据撑不起判断"的说明。
    condition: str = Field(default="", max_length=120)
    fund_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=3)


class AgentAnalysis(BaseModel):
    """Model output; the server adds the sender, task, round and coverage."""

    model_config = ConfigDict(extra="forbid")
    findings: list[EvidenceFinding] = Field(default_factory=list, max_length=6)
    gaps: list[GapText] = Field(default_factory=list, max_length=4)
    addressed_issue_indices: list[Annotated[int, Field(ge=0, le=5, strict=True)]] = Field(
        default_factory=list, max_length=6
    )
    stance: DimensionStance | None = None


class AgentReport(BaseModel):
    """Immutable envelope used by the graph's shared result channel."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    role: ResearchRole
    round: Literal[1, 2]
    status: Literal["completed", "partial", "failed", "skipped"]
    analysis: AgentAnalysis = Field(default_factory=AgentAnalysis)
    coverage: TaskCoverage | None = None
    skip_reason: (
        Literal["not_applicable", "no_verified_positions", "not_required", "previous_failed", "budget"] | None
    ) = None


def merge_agent_reports(left: list[AgentReport], right: list[AgentReport]) -> list[AgentReport]:
    """Merge parallel writes deterministically; replay is idempotent, conflicts fail closed."""
    reports: dict[tuple[str, str, int], AgentReport] = {}
    for value in [*left, *right]:
        item = AgentReport.model_validate(value)
        key = (item.run_id, item.role, item.round)
        if key in reports and reports[key] != item:
            raise ValueError("conflicting research agent envelope")
        reports[key] = item
    if len({item.run_id for item in reports.values()}) > 1:
        raise ValueError("research agent envelopes belong to different runs")
    return [reports[key] for key in sorted(reports)]


class ReviewIssue(BaseModel):
    """Feedback targets a real claim in a particular role's first-round report."""

    model_config = ConfigDict(extra="forbid")
    role: ResearchRole
    finding_index: int = Field(ge=0, le=5, strict=True)
    reason: str = Field(min_length=1, max_length=500)
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=6)


class SupplementRequest(BaseModel):
    """The server constructs tool arguments; the reviewer cannot supply arbitrary calls."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["announcements", "managers", "market_events"]
    fund_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    reason: str = Field(min_length=1, max_length=300)


class ResearchReview(BaseModel):
    """Bounded reviewer feedback, delivered only after all role reports have arrived."""

    model_config = ConfigDict(extra="forbid")
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=6)
    supplements: list[SupplementRequest] = Field(default_factory=list, max_length=2)
    gaps: list[GapText] = Field(default_factory=list, max_length=4)


class ResearchProgress(BaseModel):
    """Public stage information, without agent output or private reasoning."""

    kind: Literal["research_progress"] = "research_progress"
    run_id: str
    stage: ResearchStage
    role: ResearchRole | None = None
    status: Literal["started", "completed", "partial", "failed", "skipped"]


class ResearchActivity(BaseModel):
    """One-line live ticker for a running role: the tail of its reasoning, never the answer.

    只给一行空间的展示文本，所以长度有硬上限；正文与结构化结果仍走各自的通道。
    """

    kind: Literal["research_activity"] = "research_activity"
    run_id: str
    stage: ResearchStage
    role: ResearchRole | None = None
    text: str = Field(default="", max_length=200)


class ResearchRoleOutcome(BaseModel):
    """一份多角色报告里每个角色的实际结局，界面据此显示"N 个角色里 M 个失败".

    这些数字来自服务端信封（``AgentReport.status``），不是模型在正文里的自述。
    """

    role: ResearchRole
    status: Literal["completed", "partial", "failed", "skipped"]


AgentReports = Annotated[list[AgentReport], merge_agent_reports]
