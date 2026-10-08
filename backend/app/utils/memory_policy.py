"""记忆范围与召回的纯规则；验证 LLM 结果，绝不把系统或工具输出当用户事实."""

import hashlib
import re

from app.schemas.semantic_memory import MemoryOperation

_SENSITIVE = re.compile(r"api[ _-]?key|sk-[a-z0-9]{8,}|bearer\s+\S+|password|密码|身份证|银行卡", re.I)
_INSTRUCTION = re.compile(r"忽略.*(?:规则|指令)|系统提示词|system prompt|绕过|无需确认|自动确认|交易授权", re.I)
_HYPOTHETICAL = re.compile(r"假设|假如|假定|虚构|如果我|比如我|举个例子")
_PROFILE_TEXT = re.compile(
    r"(?:我的?|本人).{0,8}(?:风险偏好|风险承受|投资目标|投资期限|投资经验)|(?:我|本人).{0,4}(?:偏保守|偏激进|是新手)|(?:用|使用)(?:中文|英文).{0,4}(?:回答|回复)|risk (?:preference|tolerance)",
    re.I,
)
_DYNAMIC = re.compile(
    r"我持有|我的持仓|持仓金额|份额|净值(?:为|是)|收益率(?:为|是)|市值|已买入|已卖出|本金|\d[\d,.]*\s*(?:元|万元|份|%)"
)
_PROFILE_KEYS = {
    "response_language",
    "response_detail",
    "investment_experience",
    "risk_preference",
    "investment_horizon_months",
    "investment_goals",
    "excluded_fund_types",
}
_MEMORY_CUE = re.compile(r"记得|记住|回忆|上次|之前|以前|当时|偏好|历史|纠正|更正|忘记|删除记忆")
_GREETING = re.compile(r"^(?:你好|您好|谢谢|好的|hi|hello|thanks|ok)[\s!！。.?？]*$", re.I)
_PREFERENCE = re.compile(r"偏好|喜欢|更关注|优先|侧重|重点|倾向|感兴趣|只看|prefer|focus", re.I)
_PAST = re.compile(r"之前|上次|曾经|昨天|前天|过去|last |previous|\d{4}-\d{2}-\d{2}", re.I)


def should_extract(text: str) -> bool:
    """只对有偏好、历史分析或遗忘线索的声明排队，普通问答不消耗提取模型."""
    if not allowed_text(text) or re.search(r"[?？]|要不要|是否|是不是|吗[。！!\s]*$|你(?:还)?记得|哪些|能不能", text):
        return False
    if re.search(r"忘记|删除记忆|不要再记|forget|delete memory", text, re.I):
        return True
    if _PREFERENCE.search(text):
        return True
    return bool(_PAST.search(text) and re.search(r"分析|比较|研究|观察|决定|review|compar|analys", text, re.I))


def message_key(session_id: str, message_id: str) -> str:
    """来源身份构成稳定幂等键；不以相同文本误判用户重复表达."""
    return hashlib.sha256(f"{session_id}\0{message_id}".encode()).hexdigest()


def key_hash(operation: MemoryOperation) -> str:
    """语义键只存不可读哈希，删除条目后不保留明文主题."""
    return hashlib.sha256(f"{operation.kind}:{operation.key}".encode()).hexdigest()


def allowed_text(text: str) -> bool:
    """保守过滤敏感信息、假设、权限指令和实际资产数值."""
    return bool(text.strip()) and not any(
        rule.search(text) for rule in (_SENSITIVE, _INSTRUCTION, _HYPOTHETICAL, _DYNAMIC, _PROFILE_TEXT)
    )


def validate_operation(operation: MemoryOperation, user_text: str) -> bool:
    """证据必须来自本条新增用户消息；删除还必须有明确遗忘意图."""
    if operation.source_quote not in user_text or operation.key in _PROFILE_KEYS:
        return False
    if not allowed_text(operation.source_quote):
        return False
    if operation.action == "delete":
        return bool(re.search(r"忘记|删除|不再记|不要再记|forget|delete", user_text, re.I))
    if not allowed_text(operation.content) or operation.content not in user_text:
        return False
    if operation.kind == "research_preference":
        return bool(_PREFERENCE.search(operation.content))
    return bool(_PAST.search(operation.content))


def should_retrieve(query: str) -> bool:
    """记忆意图优先；寒暄、纯日历或纯实时金融查询跳过语义召回."""
    query = query.strip()
    if not query or _GREETING.fullmatch(query) or _SENSITIVE.search(query) or _INSTRUCTION.search(query):
        return False
    if _MEMORY_CUE.search(query):
        return True
    if re.search(r"节假日|放假|调休|补班|星期几", query):
        return False
    if re.search(r"净值|估值|行情|今天.*涨|实时.*收益", query) and not re.search(r"分析|对比|比较|策略|推荐", query):
        return False
    return True
