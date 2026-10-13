"""明确任务的无模型快速路径；歧义和复合请求留给主模型结构化工具调用."""

import re

from app.schemas.research import AllocationAction, ResearchRequest

_CODES = re.compile(r"(?<!\d)\d{6}(?!\d)")
_RESEARCH = re.compile(r"分析|研究|诊断|潜力|涨跌原因|为什么.*(?:涨|跌)")
_NEGATED = re.compile(r"(?:不要|不用|别|不需要).{0,8}(?:分析|诊断|研究|导入|同步|加仓|减仓|建仓)")
_ACTION_WORDS: dict[str, AllocationAction] = {"建仓": "build", "加仓": "increase", "减仓": "reduce", "清仓": "exit"}


def request_after_fund_selection(text: str, codes: list[str]) -> ResearchRequest | None:
    """对象已由用户/精确搜索确认，直接恢复明确研究需求，不再让模型重新规划."""
    if not codes or len(codes) > 3 or _NEGATED.search(text) or re.search(r"导入|同步持仓|更新持仓|解释|什么是", text):
        return None
    actions: list[AllocationAction] = [action for word, action in _ACTION_WORDS.items() if word in text]
    if not actions and not re.search(r"分析|研究|潜力|怎么样|如何|值得", text):
        return None
    account = re.search(r"(?:账户|账号)\s*(?:ID|id|编号)?\s*[：:#]?\s*(\d+)(?!\d)", text)
    if re.search(r"账户|账号", text) and (account is None or int(account.group(1)) <= 0):
        return None  # 未确认的账户名称仍需要澄清，不能改为全账户范围。
    amount = None
    if len(codes) == 1 and len(actions) == 1:
        amounts = {
            float(match.group(1).replace(",", "")) * (10000 if match.group(2) == "万元" else 1)
            for match in re.finditer(r"(?<![\d.,])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(万元|元)", text)
        }
        supplied = [
            value
            for value in amounts
            if explicitly_supplied_operation_amount(text, value) and 0 < value <= 1_000_000_000
        ]
        amount = supplied[0] if len(supplied) == 1 else None
    action: AllocationAction | None = None
    if len(actions) == 1:
        action = actions[0]
    elif actions:
        action = "compare"
    return ResearchRequest(
        intent="allocation_analysis" if actions else "fund_research",
        fund_queries=codes,
        mode="deep" if re.search(r"深度|深入|详细|全面", text) else "standard",
        account_id=int(account.group(1)) if account and int(account.group(1)) > 0 else None,
        action=action,
        proposed_amount=amount,
    )


def infer_research_request(text: str) -> ResearchRequest | None:
    """仅自动路由代码明确的研究和明确本人组合诊断，不猜名称或隐含操作."""
    if _NEGATED.search(text) or re.search(r"导入|同步持仓|更新持仓|解释|什么是|是什么意思", text):
        return None
    actions = [action for word, action in _ACTION_WORDS.items() if word in text]
    codes = list(dict.fromkeys(_CODES.findall(text)))
    if len(codes) > 3 or len(actions) > 1:
        return None
    mode = "deep" if re.search(r"深度|深入|详细|全面", text) else "standard"
    if actions:
        # 自然语言金额和账户范围由主模型提取后交给路由器核对，不在这里猜测。
        return None
    symbols = re.findall(
        r"(?<![A-Za-z0-9.])(?:sh\d{6}|sz\d{6}|bj\d{6}|hk\d{5}|us[A-Z][A-Z.]{0,10})(?![A-Za-z0-9.])", text
    )
    if symbols:
        if len(set(symbols)) == 1 and _RESEARCH.search(text) and not re.search(r"账户|账号|持仓|成本|基金", text):
            return ResearchRequest(intent="stock_research", mode=mode, stock_symbol=symbols[0])
        return None
    sectors = re.findall(r"BK\d{4,6}(?!\d)", text)
    if sectors:
        if len(set(sectors)) == 1 and _RESEARCH.search(text) and not codes:
            return ResearchRequest(intent="sector_research", mode=mode, sector_query=sectors[0])
        return None
    if re.search(r"股票|个股|板块|行业|概念", text):
        return None
    if re.search(r"我的持仓|我的组合|整个组合|持仓诊断|组合诊断", text) and _RESEARCH.search(text):
        if codes or re.search(r"账户|账号|组合[一二三四五六七八九]|账户\s*\d", text):
            return None
        return ResearchRequest(intent="portfolio_diagnosis", mode=mode)
    if codes and _RESEARCH.search(text):
        if re.search(r"账户|账号|持仓|成本|盈亏|加仓|减仓|建仓|买入|卖出", text):
            return None
        return ResearchRequest(intent="fund_research", mode=mode, fund_queries=codes)
    return None


def explicitly_supplied_amount(text: str, amount: float) -> bool:
    """金额只接受用户实际给出的元/万元数值，不把比例或基金代码转换成金额."""
    for match in re.finditer(r"(?<![\d.,])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(万元|元)", text):
        value = float(match.group(1).replace(",", "")) * (10000 if match.group(2) == "万元" else 1)
        if abs(value - amount) < 0.005:
            return True
    return False


def explicitly_supplied_operation_amount(text: str, amount: float) -> bool:
    """已有成本、市值和可用资金不自动等于拟操作金额，须与操作在同一语句."""
    for clause in re.split(r"[，。；;\n！？!?]|(?<!\d),(?!\d)", text):
        if not re.search(r"建仓|加仓|减仓|清仓|买入|卖出|申购|赎回|投入|投资", clause):
            continue
        for match in re.finditer(r"(?<![\d.,])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(万元|元)", clause):
            if re.search(
                r"(?:成本|市值|本金|已投入|持有金额|可用资金|余额)\s*(?:为|是|有|约|共|：|:)?\s*$",
                clause[: match.start()],
            ):
                continue
            if explicitly_supplied_amount(match.group(0), amount):
                return True
    return False
