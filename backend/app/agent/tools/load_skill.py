"""按需加载可信内置技能，保持系统提示词前缀精简."""

from langchain_core.tools import tool

from app.agent.skills import read_skill
from app.agent.tools.common import tool_result
from app.agent.tools.result import ToolResult
from app.schemas.agent_skill import LoadSkillRequest, SkillName, SkillSection


@tool(args_schema=LoadSkillRequest)
@tool_result
async def load_skill(skill_name: SkillName, section: SkillSection = "instructions") -> ToolResult:
    """加载开发者维护的只读内置skill流程或资源；不代表分析已完成.

    portfolio-diagnosis适用于“诊断我的持仓”“组合是否合理”“持仓太集中/重复买了吗/如何调整”。
    fund-analysis适用于指定基金潜力、近期涨跌原因和后续策略的完整研究。
    fund-comparison适用于两到三只基金横向对比，量化指标使用共同日期窗口计算工具。
    fund-allocation适用于基金建仓/加减仓方案；sector-analysis研究A股板块，stock-analysis研究已确认市场代码的股票。
    先加载instructions，需要工具证据与图表协议时加载evidence；简单净值查询无需加载。
    不访问外部URL、任意路径或执行脚本；不会取得用户身份、读取持仓或修改账户。
    内置流程从属于系统规则和本轮需求，不授权交易或绕过确认。
    """
    return ToolResult.ok(read_skill(skill_name, section).model_dump(mode="json"), source="builtin_skill_registry")
