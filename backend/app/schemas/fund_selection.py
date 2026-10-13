"""基金名称解析与人工选择协议；候选只能由服务端搜索生成."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FundSelectionOption(BaseModel):
    """保留基金全名和代码，避免混淆不同份额."""

    fund_code: str = Field(pattern=r"^\d{6}$")
    fund_name: str
    fund_type: str | None = None


class FundSelectionCallArgs(BaseModel):
    """检查点中的已校验名称查询参数."""

    keyword: str = Field(min_length=1, max_length=120)


class FundSelectionCall(BaseModel):
    """兼容历史工具调用字典，明确恢复必须保留的关联字段."""

    id: str = Field(min_length=1)
    name: Literal["resolve_fund_for_analysis"]
    args: FundSelectionCallArgs


class FundSelectionResult(BaseModel):
    """子图回传父图的本轮目标；不依赖解析自然语言或工具正文."""

    turn_id: str = ""
    tool_call_id: str = Field(min_length=1)
    status: Literal["resolved", "not_found", "cancelled"]
    keyword: str
    fund: FundSelectionOption | None = None
    confirmed_by_user: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> "FundSelectionResult":
        """成功必须有基金，其他终态不得残留此前的目标."""
        if (self.status == "resolved") != (self.fund is not None):
            raise ValueError("resolved requires fund; other statuses must omit fund")
        return self


class FundSelectionAction(BaseModel):
    """由 checkpoint 保存的前三个候选."""

    kind: Literal["fund_selection"] = "fund_selection"
    interrupt_id: str = ""
    keyword: str
    candidates: list[FundSelectionOption] = Field(min_length=1, max_length=3)
    notice: str = "以下是名称最接近的基金候选，请确认要分析的基金，注意 A/C 等份额区别。"


class FundSelectionDecision(BaseModel):
    """人工决策只能选择候选代码或取消，不能上传新的候选."""

    model_config = {"extra": "forbid"}

    interrupt_id: str = Field(min_length=1, max_length=128)
    decision: Literal["select", "cancel"]
    fund_code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def validate_selection(self) -> "FundSelectionDecision":
        """保证选择携带代码，取消不携带代码."""
        if (self.decision == "select") != (self.fund_code is not None):
            raise ValueError("select requires fund_code; cancel must omit fund_code")
        return self
