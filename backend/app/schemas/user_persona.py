"""用户画像的白名单字段、候选更新及人工决策协议."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=120)]
FundType = Literal["equity", "bond", "money_market", "mixed", "index", "qdii", "fof", "reit", "commodity"]


class PersonaFields(BaseModel):
    """只表示用户声明的偏好；不包含持仓、金额、凭证或交易授权."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    response_language: Literal["zh-CN", "en"] | None = None
    response_detail: Literal["concise", "balanced", "detailed"] | None = None
    investment_experience: Literal["beginner", "intermediate", "experienced"] | None = None
    risk_preference: Literal["conservative", "balanced", "aggressive"] | None = None
    investment_horizon_months: Annotated[int, Field(ge=1, le=600)] | None = None
    investment_goals: Annotated[list[ShortText], Field(max_length=5)] | None = None
    excluded_fund_types: Annotated[list[FundType], Field(max_length=9)] | None = None


class PersonaPatch(PersonaFields):
    """部分更新；显式 null 删除字段，省略字段保持原值."""

    @model_validator(mode="after")
    def require_changes(self) -> "PersonaPatch":
        """拒绝空更新，避免无意义推进版本."""
        if not self.model_fields_set:
            raise ValueError("至少提供一个画像字段")
        return self


class PersonaUpdate(BaseModel):
    """用户直接编辑已确认画像，必须携带读到的版本."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    changes: PersonaPatch


class PersonaDecision(BaseModel):
    """只允许人工 HTTP 接口确认或拒绝候选."""

    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject"]
    expected_revision: int = Field(ge=0, strict=True)


class PersonaClear(BaseModel):
    """画像清除协议，版本保护并发更新."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)


class PersonaProposalOut(BaseModel):
    """候选只作为复核数据返回，不参与回答上下文."""

    id: str
    base_revision: int
    changes: dict
    evidence: str
    source_session_id: str
    source_message_id: str
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "SUPERSEDED"]
    created_at: datetime


class PersonaOut(BaseModel):
    """已确认画像、来源与当前待确认候选."""

    revision: int = 0
    fields: PersonaFields = Field(default_factory=PersonaFields)
    provenance: dict[str, dict] = Field(default_factory=dict)
    pending_proposals: list[PersonaProposalOut] = Field(default_factory=list)


class PersonaHistoryOut(BaseModel):
    """一次已提交变更的版本与来源；清除画像时一并删除."""

    revision: int
    changes: dict
    source: str
    proposal_id: str | None = None
    created_at: datetime
