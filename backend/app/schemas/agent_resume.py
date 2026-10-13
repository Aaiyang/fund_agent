"""已授权任务在执行失败后继续，不重新提交人工决定或新用户消息."""

from pydantic import BaseModel, ConfigDict, Field


class AgentRunContinuation(BaseModel):
    """checkpoint中尚未完成且不等待人工决定的原任务."""

    turn_id: str
    notice: str = "原任务尚未完成，可继续执行；已经确认的对象和操作会保留。"
    selected_fund_code: str | None = None
    selected_fund_name: str | None = None


class AgentContinueRequest(BaseModel):
    """旧界面不得推进另一轮任务，身份始终由会话令牌决定."""

    model_config = ConfigDict(extra="forbid")
    turn_id: str = Field(min_length=1, max_length=128)
