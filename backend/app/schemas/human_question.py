"""通用人工问答的可恢复展示协议，不承载持仓写入授权."""

from typing import Literal

from pydantic import BaseModel


class HumanQuestionAction(BaseModel):
    """刷新后仍能看到真实问题；回答通过原会话聊天入口恢复."""

    kind: Literal["human_question"] = "human_question"
    interrupt_id: str = ""
    question: str
    notice: str = "请在输入框回答，发送后会继续原任务。"
