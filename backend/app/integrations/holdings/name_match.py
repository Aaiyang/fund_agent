"""基金名称匹配：截图上的名称对着名册能算几分.

截图很少印出 6 位代码，印出来的名称又是 App 自己的简写——半角或全角括号、可有
可无的 (QDII) 标签、币种变体，有时还被省略号截断。所以比的是归一化之后的名称，
而且只有归一化后恰好剩一只基金时才说它匹配上了。

比完还剩好几个份额类别是常态，不是错误：支付宝显示「广发纳斯达克100ETF联接…」，
而 A/C/人民币/美元 是四只不同的基金。这种结果要带着候选回到复核页让用户挑——
替他选一只，就是把另一只基金的钱记进了他的流水。
"""

import re
import unicodedata
from dataclasses import dataclass

# 平台展示名可能多写或少写一些词，指的还是同一只基金：支付宝写作
# 「嘉实信息产业股票C」「华泰柏瑞质量成长混合C」，名册里却叫
# 「…发起式C」「…质量成长C」。2025 年交易所走了相反的方向，
# 要求 ETF 简称里带上管理人名称，讲的也是同一个道理：
# 名称只是标签，代码才是身份。
_STRIP_TAGS = re.compile(
    r"(qdii|qd2|人民币|美元|现汇|现钞|份额|发起式|混合型|混合|股票型|股票|债券型|债券|指数|证券投资基金)"
)
# 结尾那个标出份额类别的字母：混合C、联接A、指数E。它不能是一个缩略词的最后一个
# 字母——「招商快线ETF」并没有份额类别——而且要先把结尾的括号跳掉，
# 这样「华夏大盘精选混合A(后端)」仍然读得出 A。
_SHARE_CLASS = re.compile(r"(?<![a-z])([a-f])$")
_TRAILING_BRACKET = re.compile(r"[()（）\s]+$|[（(][^（）()]*[)）]$")
_PUNCTUATION = re.compile(r"[\s·•.,，、:：;；'’“”\"()（）\-—_]+")


@dataclass(frozen=True)
class NameMatch:
    """名册里的一条记录对着目标名称打出来的分."""

    fund_code: str
    fund_name: str
    score: float

    @property
    def share_class(self) -> str | None:
        """这只基金名称结尾的 A/C/E 字母，没有就是 None."""
        return share_class_of(self.fund_name)


def fold(text: str) -> str:
    """名称转小写并去掉展示标签，但把标点留着.

    份额类别那条规则要把标点边界拿回来，才能分清「(LOF)C」（C 类）和
    「ETF」（没有类别），所以它读的是这个结果，而不是 `normalize`。
    """
    return _STRIP_TAGS.sub("", unicodedata.normalize("NFKC", text).lower())


def normalize(text: str) -> str:
    """把名称折叠成比对真正使用的那个形式."""
    return _PUNCTUATION.sub("", fold(text))


def share_class_of(text: str) -> str | None:
    """名称结尾的份额类别字母，统一转成小写."""
    folded = fold(text)
    while (trimmed := _TRAILING_BRACKET.sub("", folded)) != folded:
        folded = trimmed
    match = _SHARE_CLASS.search(folded)
    return match.group(1) if match else None


def _common_prefix(left: str, right: str) -> int:
    """两个名称开头连续相同多少个字符."""
    return next(
        (index for index, (a, b) in enumerate(zip(left, right, strict=False)) if a != b), min(len(left), len(right))
    )


def _prefix_score(wanted: str, candidate: str) -> float:
    """一个可能被截断或读错的名称，与名册里的名称贴合到什么程度."""
    if wanted == candidate:
        return 1.0
    if candidate.startswith(wanted) or wanted.startswith(candidate):
        shorter, longer = sorted((wanted, candidate), key=len)
        missing = (len(longer) - len(shorter)) / max(len(longer), 1)
        return round(0.95 - missing * 0.6, 4)
    # 被屏幕下边缘截掉的那一行，往往也是 OCR 读得最差的一行：
    # 「ETF联接C」读回来成了「CTC联培C」。共同的前缀够用来给出候选，
    # 但绝不够用来自动采纳。
    shared = _common_prefix(wanted, candidate)
    if shared >= 4:
        return round(0.9 * shared / max(len(wanted), len(candidate)), 4)
    if wanted in candidate or candidate in wanted:
        return 0.55
    return 0.0


def score_name(wanted: str, candidate: str) -> float:
    """两个基金名称的相似度，认定是不同基金时给 0.

    份额类别不一样就直接出局：「联接C」和「联接A」各自都跟被截断的「联接」对得上，
    但它俩永远对不上。
    """
    wanted_class = share_class_of(wanted)
    candidate_class = share_class_of(candidate)
    if wanted_class and candidate_class and wanted_class != candidate_class:
        return 0.0
    return _prefix_score(normalize(wanted), normalize(candidate))


def rank_names(
    wanted: str, directory: list[tuple[str, str]], limit: int = 5, min_score: float = 0.5
) -> list[NameMatch]:
    """整个名册对着一个名称逐个打分，最好的排在前面.

    Args:
        wanted: 从截图上读出来的那个名称。
        directory: 要搜索的 (code, name) 二元组列表。
        limit: 返回多少个候选。
        min_score: 低于这个分的是噪音，算不上候选。
    """
    wanted_clean = (wanted or "").strip()
    if not wanted_clean:
        return []

    matches: list[NameMatch] = []
    for code, name in directory:
        value = score_name(wanted_clean, name)
        if value >= min_score:
            matches.append(NameMatch(fund_code=code, fund_name=name, score=value))
    # 分数高的在前，同分时名称短的在前：两个都匹配时，联接C 要压过 联接C人民币。
    matches.sort(key=lambda match: (-match.score, len(match.fund_name), match.fund_code))
    return matches[:limit]


def decide(matches: list[NameMatch], auto_accept: float = 0.95) -> NameMatch | None:
    """名称唯一解析到的那一只基金；该由用户来挑时返回 None.

    候选是按基金比，不是按拼写比：名册里对同一个代码故意同时留着登记的简称和同步
    来的全称，一旦两者折叠成同一形式，按拼写比这只基金就成了自己的亚军，等它的
    全称记录落库那天就再也匹配不上了。只有相差 0.05 以内的*另一个代码*才算歧义
    ——那是份额类别，选错就是把真金白银记到了别的基金账上。
    """
    best_by_code: dict[str, NameMatch] = {}
    for match in matches:
        current = best_by_code.get(match.fund_code)
        if current is None or match.score > current.score:
            best_by_code[match.fund_code] = match
    ranked = sorted(best_by_code.values(), key=lambda match: -match.score)
    if not ranked:
        return None
    best = ranked[0]
    if best.score < auto_accept:
        return None
    if len(ranked) > 1 and ranked[1].score >= best.score - 0.05:
        return None
    return best
