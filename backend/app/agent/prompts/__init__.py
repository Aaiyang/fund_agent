"""Agent 的提示词模板加载器."""

# 系统提示词版本：仅当身份/规则/工具使用原则变化时升级（KV Cache 前缀稳定性）
# v2：agent_name 修正（去掉重复的 " Agent"）——身份变化
# v4：节假日与调休查询必须使用日历工具，禁止联网搜索兜底
SYSTEM_PROMPT_VERSION = "fund-agent-v4"

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
        # PROJECT_NAME 本身已含 "Agent"，再拼一次会让模型自称 "Fund Agent Agent"
        agent_name=settings.PROJECT_NAME,
        user_context=user_context,
        **kwargs,
    )
