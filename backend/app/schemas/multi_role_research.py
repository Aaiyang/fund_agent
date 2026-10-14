"""Bounded, task-scoped communication between research agents."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ResearchRole = Literal["fundamentals", "risk", "portfolio"]
ResearchStage = Literal["evidence", "analysis", "review", "supplement", "revision", "report"]
GapText = Annotated[str, Field(min_length=1, max_length=500)]
EvidenceId = Annotated[str, Field(min_length=1, max_length=64)]
TaskId = Annotated[str, Field(min_length=1, max_length=100)]


class ResearchAssignment(BaseModel):
    """Server-owned completion criteria, scoped to a role and confirmed objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: TaskId
    role: ResearchRole
    fund_code: str | None = None
    description: str
    required_tool_groups: list[list[str]] = Field(default_factory=list)


class TaskCoverage(BaseModel):
    """A task is covered by actual findings or explicitly blocked by a data gap."""

    model_config = ConfigDict(extra="forbid")
    task_id: TaskId
    status: Literal["completed", "blocked"]
    finding_indices: list[Annotated[int, Field(ge=0, le=3, strict=True)]] = Field(default_factory=list, max_length=4)
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=6)
    explanation: str = Field(min_length=1, max_length=300)


class EvidenceFinding(BaseModel):
    """A claim references server-issued evidence IDs, never another agent's prose."""

    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1, max_length=700)
    kind: Literal["fact", "inference", "conditional"]
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=6)
    limitation: str = Field(max_length=500)


class AgentAnalysis(BaseModel):
    """Model output; the server adds the sender, task and round."""

    model_config = ConfigDict(extra="forbid")
    findings: list[EvidenceFinding] = Field(default_factory=list, max_length=4)
    gaps: list[GapText] = Field(default_factory=list, max_length=4)
    coverage: list[TaskCoverage] = Field(default_factory=list, max_length=4)
    addressed_issue_indices: list[Annotated[int, Field(ge=0, le=5, strict=True)]] = Field(
        default_factory=list, max_length=6
    )


class AgentReport(BaseModel):
    """Immutable envelope used by the graph's shared result channel."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    role: ResearchRole
    round: Literal[1, 2]
    status: Literal["completed", "partial", "failed", "skipped"]
    analysis: AgentAnalysis = Field(default_factory=AgentAnalysis)
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
    finding_index: int = Field(ge=0, le=3, strict=True)
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
