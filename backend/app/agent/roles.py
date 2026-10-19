"""研究维度的对外称呼：维度名与归属人，唯一来源.

以前维度名写在 ``research_contract.ROLE_LABELS``、职务名写在 ``ROLE_BRIEFS`` 的字面量开头、
移动端再抄一份，三处各自演化过。收拢到这里，键集一致性由测试钉住
（见 ``tests/test_multi_role_contract.py`` 的词表单源用例）。
"""

from app.schemas.multi_role_research import ResearchRole

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
