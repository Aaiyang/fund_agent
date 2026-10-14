"""内置只读技能与其明确白名单资源."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SkillName = Literal[
    "fund-analysis", "fund-comparison", "portfolio-diagnosis", "fund-allocation", "sector-analysis", "stock-analysis"
]
SkillSection = Literal["instructions", "evidence"]


class LoadSkillRequest(BaseModel):
    """不允许URL、任意文件路径或可执行脚本输入."""

    model_config = ConfigDict(extra="forbid")
    skill_name: SkillName = Field(
        description="基金研究、基金对比、持仓诊断、基金操作方案、板块研究或股票研究的内置技能"
    )
    section: SkillSection = Field(
        default="instructions", description="instructions加载流程；evidence加载工具证据与图表协议"
    )


class LoadedSkill(BaseModel):
    """开发者维护的内置流程，不接受用户自定义指令覆盖."""

    name: SkillName
    version: str
    section: SkillSection
    content: str
    available_sections: list[SkillSection]
