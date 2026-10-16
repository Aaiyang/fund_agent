"""应用的对话相关 schema 定义."""

import re
from typing import (
    Annotated,
    List,
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.base import BaseResponse
from app.schemas.agent_import import AgentPendingAction, ImportId
from app.schemas.agent_resume import AgentRunContinuation
from app.schemas.multi_role_research import ResearchActivity, ResearchProgress, ResearchRoleOutcome
from app.schemas.research import ResearchIntent

# 客户端研究入口的对象只能是六位代码，不接受名称（名称要经解析节点确认）
ResearchFundCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class Message(BaseModel):
    """服务端内部、回答与历史消息，不套用客户端输入的长度或正文校验.

    Attributes:
        role: 消息发送方角色（user 或 assistant）。
        content: 消息正文。
    """

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"] = Field(..., description="The role of the message sender")
    # 模型输出长度由生成 token 预算控制；历史必须能原样返回已保存的正文。
    content: str = Field(..., description="The complete content of the message", min_length=1)
    research_id: str | None = Field(default=None, description="服务端签发的可进一步研究的报告标识")
    research_intent: ResearchIntent | None = Field(
        default=None, description="该报告的研究对象类型，界面据此决定按钮写「深度研究」还是「深度对比」"
    )
    # 多角色报告的结局由服务端信封决定，界面用它做徽标；正文里模型自己怎么说都不算数。
    research_roles: list[ResearchRoleOutcome] | None = Field(
        default=None, description="多角色报告里每个角色的实际结局；单档位报告为 None"
    )
    research_review_status: Literal["completed", "partial", "failed", "skipped"] | None = Field(
        default=None, description="多角色报告的交叉审核结局"
    )


class ChatInputMessage(BaseModel):
    """客户端输入独立校验：仅用户角色，正文最多 3000 字符."""

    role: Literal["user"]
    content: str = Field(..., min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """校验客户端输入正文，不影响回答及已保存的历史内容.

        Args:
            v: 待校验的正文

        Returns:
            str: 校验通过的正文

        Raises:
            ValueError: 正文里出现不允许的内容时抛出
        """
        # 拦掉可能有危害的内容
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")

        # 拦掉空字节
        if "\0" in v:
            raise ValueError("Content contains null bytes")

        return v


class ChatRequest(BaseModel):
    """chat 端点的请求模型.

    Attributes:
        messages: 本次对话的消息列表。
    """

    messages: List[ChatInputMessage] = Field(
        ...,
        description="List of messages in the conversation",
        min_length=1,
    )
    holding_import_ids: list[ImportId] = Field(default_factory=list, max_length=5)
    holding_account_id: int | None = Field(default=None, gt=0)
    research_followup_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    research_fund_codes: list[ResearchFundCode] = Field(
        default_factory=list,
        max_length=3,
        description="客户端选基金面板直接授权的研究对象；只能是六位基金代码",
    )
    research_strategy: Literal["single", "multi_role"] = Field(
        default="single",
        description="成本档位：single 一次模型出报告，multi_role 三角色合议（仅随 research_fund_codes 生效）",
    )

    @model_validator(mode="after")
    def valid_research_followup(self) -> "ChatRequest":
        """A follow-up uses the source's scope, without competing attachment or account inputs."""
        if self.research_followup_id and (
            self.holding_import_ids or self.holding_account_id is not None or len(self.messages) != 1
        ):
            raise ValueError("进一步研究不能与附件、账户变更或多条新消息混合提交")
        return self

    @model_validator(mode="after")
    def valid_client_research_request(self) -> "ChatRequest":
        """客户端研究入口只接受代码，且单独发起：附件、账户变更、追问都不能同行."""
        if self.research_strategy == "multi_role" and not self.research_fund_codes:
            raise ValueError("多智能体档位需要同时给出研究对象代码")
        if not self.research_fund_codes:
            return self
        if len(set(self.research_fund_codes)) != len(self.research_fund_codes):
            raise ValueError("研究的基金代码不能重复")
        if (
            self.holding_import_ids
            or self.holding_account_id is not None
            or self.research_followup_id
            or len(self.messages) != 1
        ):
            raise ValueError("发起研究需要单独提交，不能与附件、账户变更或追问混合")
        return self


class ChatResponse(BaseResponse):
    """chat 端点的响应模型.

    Attributes:
        messages: 本次对话的消息列表。
    """

    messages: List[Message] = Field(..., description="List of messages in the conversation")
    pending_action: AgentPendingAction | None = None
    continuation: AgentRunContinuation | None = None


class StreamResponse(BaseResponse):
    """流式 chat 端点的响应模型.

    Attributes:
        content: 当前这一段的内容。
        done: 整条流是否已经结束。
    """

    content: str = Field(default="", description="The content of the current chunk")
    done: bool = Field(default=False, description="Whether the stream is complete")
    pending_action: AgentPendingAction | None = None
    continuation: AgentRunContinuation | None = None
    research_progress: ResearchProgress | None = None
    research_activity: ResearchActivity | None = Field(
        default=None, description="角色调用的一行滚动摘要（思考尾部），只给一行空间的界面用"
    )


class HoldingImportDecisionResponse(ChatResponse):
    """人工操作结果由数据库确定，客户端不依赖模型生成的成功描述."""

    import_id: ImportId
    status: Literal["APPLIED", "CANCELLED"]
    applied: int
    skipped: int


class SessionTitle(BaseModel):
    """会话标题生成所用的结构化输出 schema."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=60,
    )

    @field_validator("title")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = " ".join(v.split()).strip(" \"'`.,:;!?-")
        if not v:
            raise ValueError("empty title after normalization")
        return v
