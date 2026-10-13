"""可解释的事件标签和基金关联规则；不推断方向、因果或收益."""

import hashlib
import re

from app.schemas.market_event import EventPositionLink, MarketEvent
from app.schemas.sector import FundSectorEvidence

# 仅为保守研究主题，不将制造业/金融业等宽披露行业猜测映射到具体行业。
TOPICS: dict[str, tuple[str, ...]] = {
    "半导体": ("半导体", "芯片", "集成电路"),
    "医药": ("医药", "生物医药", "创新药"),
    "医疗": ("医疗", "医疗器械"),
    "新能源": ("新能源",),
    "光伏": ("光伏", "太阳能"),
    "电池": ("电池", "锂电"),
    "汽车": ("汽车", "汽配", "整车"),
    "人工智能": ("人工智能", "大模型", "AI"),
    "计算机": ("计算机", "软件", "算力", "云计算"),
    "银行": ("银行",),
    "证券": ("证券", "券商"),
    "房地产": ("房地产", "地产", "楼市"),
    "军工": ("军工", "国防"),
    "农业": ("农业", "种业", "养殖"),
    "消费": ("消费", "食品", "零售"),
    "白酒": ("白酒",),
    "石油": ("石油", "原油"),
    "黄金": ("黄金", "金价"),
    "煤炭": ("煤炭", "煤价"),
    "钢铁": ("钢铁", "钢价"),
}
FACTORS = {
    "rates": ("降息", "加息", "利率", "LPR", "美联储"),
    "liquidity": ("降准", "逆回购", "流动性", "货币政策"),
    "currency": ("汇率", "人民币升值", "人民币贬值", "美元指数"),
    "trade": ("关税", "贸易", "出口管制"),
    "macro_data": ("GDP", "CPI", "PPI", "PMI", "通胀", "就业数据", "非农"),
    "fiscal": ("财政", "国债", "专项债"),
}
MARKET_TERMS = ("上证", "深证", "沪深", "创业板", "科创", "A股", "港股", "美股", "股市", "交易所", "指数", "大盘")


def _contains(text: str, token: str) -> bool:
    """短英文需词边界，避免AI匹配到普通英文词中间."""
    if token.isascii():
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", text, re.I) is not None
    return token in text


def classify_event(text: str) -> tuple[list[str], list[str], list[str]]:
    """显式词表分类，不将报道文字升级为已核验事实."""
    topics = [
        name
        for name, aliases in TOPICS.items()
        if any(
            _contains(text.replace("人民银行", "").replace("中央银行", "") if name == "银行" else text, alias)
            for alias in aliases
        )
    ]
    factors = [name for name, tokens in FACTORS.items() if any(_contains(text, token) for token in tokens)]
    categories = (["macro"] if factors else []) + (["industry"] if topics else [])
    if any(_contains(text, token) for token in MARKET_TERMS):
        categories.append("market")
    return categories, topics, factors


def event_fingerprint(source_id: str, title: str, excerpt: str, published_iso: str) -> str:
    """事件引用包含内容指纹，缓存中被改写的正文不能冒充原快照."""
    digest = hashlib.sha256((source_id + "\n" + title + "\n" + excerpt + "\n" + published_iso).encode()).hexdigest()[
        :12
    ]
    return "cls_" + source_id + "_" + digest


def link_event(event: MarketEvent, fund: FundSectorEvidence, account_id: int) -> list[EventPositionLink]:
    """先匹配披露行业，再退为名称线索；宏观/市场只构成背景关联."""
    links: list[EventPositionLink] = []
    disclosed = [
        topic
        for topic in event.topics
        if any(row.industry.removesuffix("行业").strip() in TOPICS.get(topic, ()) for row in fund.industries)
    ]
    named = [
        topic
        for topic in event.topics
        if topic not in disclosed and any(_contains(fund.fund_name, alias) for alias in TOPICS.get(topic, ()))
    ]
    common = {
        "event_id": event.event_id,
        "fund_code": fund.fund_code,
        "fund_name": fund.fund_name,
        "account_id": account_id,
    }
    if disclosed:
        links.append(
            EventPositionLink(
                **common,
                basis="disclosed_industry",
                evidence="匹配的披露行业："
                + "、".join(
                    row.industry
                    for row in fund.industries
                    if any(row.industry.removesuffix("行业").strip() in TOPICS[topic] for topic in disclosed)
                ),
                disclosure_date=fund.report_date.isoformat() if fund.report_date else None,
                matched_topics=disclosed,
                possible_channel="事件涉及基金历史披露行业；当前暴露、具体公司及作用方向仍需核验。",
            )
        )
    if named:
        links.append(
            EventPositionLink(
                **common,
                basis="fund_name_hint",
                evidence=fund.fund_name,
                matched_topics=named,
                possible_channel="基金名称与事件主题关联，仅为研究线索，不证明当前持仓暴露。",
            )
        )
    if event.factors:
        links.append(
            EventPositionLink(
                **common,
                basis="macro_context",
                evidence="事件宏观标签：" + ",".join(event.factors),
                possible_channel="宏观因素可作为研究背景；需核验基金资产类别、地区、久期或汇率暴露，不能据此确认敏感性或方向。",
            )
        )
    elif "market" in event.categories and not links:
        links.append(
            EventPositionLink(
                **common,
                basis="market_context",
                evidence="事件包含市场范围词",
                possible_channel="市场背景候选；尚未核验与基金投资地区或基准是否一致，不构成具体持仓关联。",
            )
        )
    return links
