"""研究维度的对外称呼：维度名、归属人与立场措辞，唯一来源.

以前维度名写在 ``research_contract.ROLE_LABELS``、职务名写在 ``ROLE_BRIEFS`` 的字面量开头、
移动端再抄一份，三处各自演化过。收拢到这里，键集一致性由测试钉住
（见 ``tests/test_multi_role_contract.py`` 的词表单源用例）。

立场（stance）的两个枚举也要有中文措辞：报告正文禁止出现内部键名，而代码算出来的
对立清单会被模型逐项转写，所以议题和方向都必须自带可写的名字。
"""

from app.schemas.multi_role_research import ResearchRole

# 立场议题：与 ``DimensionStance.topic`` 的枚举取值一一对应。
STANCE_TOPIC_LABELS: dict[str, str] = {
    "short_term_holding": "短期是否持有",
    "long_term_holding": "长期是否持有",
    "position_size": "仓位大小",
    "entry_timing": "建仓时点",
    "benchmark_fit": "与基准是否契合",
    "risk_budget": "风险预算",
    "information_quality": "信息质量是否够下判断",
    "team_stability": "团队稳定性",
    "other": "其他议题",
}

# 立场方向：与 ``DimensionStance.marker`` 的枚举取值一一对应。
STANCE_MARKER_LABELS: dict[str, str] = {
    "support": "支持",
    "oppose": "反对",
    "conditional": "有条件支持",
    "neutral": "不表态",
}

# 维度名：报告节标题的后半、缺口披露前缀与范围核对尾注都用它。
ROLE_LABELS: dict[ResearchRole, str] = {
    "performance": "业绩与基准契合",
    "risk": "风险与回撤",
    "holdings": "持仓与行业风格",
    "manager": "基金经理与团队",
    "disclosure": "披露与来源质量",
    "portfolio": "组合适配",
}

# 归属人：这一节由谁署名。必须与 ``ROLE_BRIEFS`` 开头的职务名一字不差。
ROLE_OWNERS: dict[ResearchRole, str] = {
    "performance": "业绩分析师",
    "risk": "风险分析师",
    "holdings": "持仓与风格分析师",
    "manager": "基金经理研究员",
    "disclosure": "披露与来源质量审查员",
    "portfolio": "组合配置顾问",
}


def section_heading(role: ResearchRole) -> str:
    """一个维度在报告里的节标题，由代码给全，模型只许逐字复制.

    形状受移动端渲染限制：``MarkdownText`` 只认 ``#{1,3}`` 加空格、不解析标题里的行内
    标记，且以数字开头的行会被当成有序列表重新编号，所以标题既不能放 ``**``，也不能写
    「一、」「1. 」这类序号。
    """
    return f"### {ROLE_OWNERS[role]}｜{ROLE_LABELS[role]}"
