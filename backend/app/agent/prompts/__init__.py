"""Agent 的提示词模板加载器."""

# 系统提示词版本：仅当身份/规则/工具使用原则变化时升级（KV Cache 前缀稳定性）
# v2：agent_name 修正（去掉重复的 " Agent"）——身份变化
# v4：节假日与调休查询必须使用日历工具，禁止联网搜索兜底
# v5：图片持仓识别与结构化人工确认
# v6：已确认用户画像与候选人工确认边界
# v7：可治理语义记忆范围、逐问题召回和异步写入状态
# v8：基金助手工作流程、工具路由、证据核验与业务边界示例
# v9：今日主要指数实时快照与历史收盘工具分工
# v10：基金板块证据与板块实时涨跌查询，禁止将主题线索当作实际持仓
# v11：按代码查询历任经理及公开公告/报告，重大变更线索需核验原文
# v12：公开事件引用与当前用户持仓关联，区分证据、线索和宏观背景
# v13：按需加载内置基金分析skill，真实一年净值图表及证据边界
# v14：附件子图等待识别、补充目标账户和独立人工复核
# v15：移动端基金研究图表、披露卡片与可核验表格呈现
# v16：仅输出基金引用，移动端直接读取后端并复用详情业绩组件
# v17：独立基金目标选择节点，不猜测基金或份额
# v18：任意基金公开研究，不以个人持仓或成本为前置条件
# v19：全名册模糊匹配与相似度 Top3；单个模糊候选也须确认
# v20：按需持仓诊断与单基金研究分流，组合数据覆盖和计算边界
# v21：本轮持仓导入意图优先，附件存在不等于导入授权
# v22：主图任务路由、有界研究子图与只读操作情景分析
# v23：固定持仓快照、按任务加载skill与股票/板块/操作图表引用
# v24：基金横向对比与共同净值窗口计算，保留数据不足及费用边界
# v25：用户显式启动多角色研究与任务内证据通信边界
SYSTEM_PROMPT_VERSION = "fund-agent-v25"

import os
from typing import Optional

from app.core.config import settings

_PROMPTS_DIR = os.path.dirname(__file__)

# 模块加载时一次性读入模板——请求期间零文件 IO
with open(os.path.join(_PROMPTS_DIR, "system.md"), encoding="utf-8") as _f:
    _SYSTEM_PROMPT_TEMPLATE = _f.read()

with open(os.path.join(_PROMPTS_DIR, "session_title.md"), encoding="utf-8") as _f:
    SESSION_TITLE_PROMPT = _f.read()


def load_prompt_file(filename: str) -> str:
    """读取指定名的提示词模板文件（缓存于模块级常量之外的按需读取）."""
    with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as prompt_file:
        return prompt_file.read()


def load_system_prompt(username: Optional[str] = None, **kwargs):
    """从缓存的模板加载系统提示词."""
    user_context = f"# User\nYou are talking to {username}.\n" if username else ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        # 助手自称走 AGENT_NAME（小镜），不用 PROJECT_NAME：那是产品名（持见），
        # 而且它本身含 "Agent"，拼进模板会让模型自称 "Fund Agent Agent"。
        agent_name=settings.AGENT_NAME,
        user_context=user_context,
        **kwargs,
    )
