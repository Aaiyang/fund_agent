"""Fund name matching: what a screenshot's name is worth against a directory.

Screenshots rarely print the 6-digit code, and the printed name is the app's
own shorthand — half-width or full-width brackets, an optional (QDII) tag, a
currency variant, sometimes cut off by an ellipsis. So names are compared on a
normalized form, and a match is only claimed when exactly one fund survives it.

Several share classes surviving the comparison is the common case, not an
error: 支付宝 shows 「广发纳斯达克100ETF联接…」 and A/C/人民币/美元 are four
different funds. Those come back as candidates for the review page to offer —
picking one for the user would put the wrong fund's money in his ledger.
"""

import re
import unicodedata
from dataclasses import dataclass

# Words a platform's display name may add or drop without changing which fund
# it means: 支付宝 writes 「嘉实信息产业股票C」 and 「华泰柏瑞质量成长混合C」 for
# funds the register calls 「…发起式C」 and 「…质量成长C」. The exchanges went the
# other way in 2025 and now require ETF short names to carry the manager's name,
# which is the same lesson: a name is a label, the code is the identity.
_STRIP_TAGS = re.compile(
    r"(qdii|qd2|人民币|美元|现汇|现钞|份额|发起式|混合型|混合|股票型|股票|债券型|债券|指数|证券投资基金)"
)
# The trailing letter that marks a share class: 混合C, 联接A, 指数E. It must not be
# the last letter of an acronym — 「招商快线ETF」 has no share class — and trailing
# brackets are skipped first so 「华夏大盘精选混合A(后端)」 still reads as A.
_SHARE_CLASS = re.compile(r"(?<![a-z])([a-f])$")
_TRAILING_BRACKET = re.compile(r"[()（）\s]+$|[（(][^（）()]*[)）]$")
_PUNCTUATION = re.compile(r"[\s·•.,，、:：;；'’“”\"()（）\-—_]+")


@dataclass(frozen=True)
class NameMatch:
    """One directory entry scored against a wanted name."""

    fund_code: str
    fund_name: str
    score: float

    @property
    def share_class(self) -> str | None:
        """The A/C/E letter this fund's name ends with, if any."""
        return share_class_of(self.fund_name)


def fold(text: str) -> str:
    """Lower-case a name and drop the display tags, keeping punctuation.

    The share-class rule needs the punctuation boundary back to tell 「(LOF)C」
    (a C class) from 「ETF」 (no class), so it reads this rather than `normalize`.
    """
    return _STRIP_TAGS.sub("", unicodedata.normalize("NFKC", text).lower())


def normalize(text: str) -> str:
    """Fold a name down to the form comparisons happen on."""
    return _PUNCTUATION.sub("", fold(text))


def share_class_of(text: str) -> str | None:
    """The share class letter a name ends with, lower-cased."""
    folded = fold(text)
    while (trimmed := _TRAILING_BRACKET.sub("", folded)) != folded:
        folded = trimmed
    match = _SHARE_CLASS.search(folded)
    return match.group(1) if match else None


def _common_prefix(left: str, right: str) -> int:
    """How many leading characters two names share."""
    return next(
        (index for index, (a, b) in enumerate(zip(left, right, strict=False)) if a != b), min(len(left), len(right))
    )


def _prefix_score(wanted: str, candidate: str) -> float:
    """How well a (possibly truncated or misread) name fits a directory name."""
    if wanted == candidate:
        return 1.0
    if candidate.startswith(wanted) or wanted.startswith(candidate):
        shorter, longer = sorted((wanted, candidate), key=len)
        missing = (len(longer) - len(shorter)) / max(len(longer), 1)
        return round(0.95 - missing * 0.6, 4)
    # A row clipped by the bottom of the screen is also the row OCR reads worst:
    # 「ETF联接C」 came back 「CTC联培C」. The shared stem is still enough to
    # offer candidates, never enough to auto-accept.
    shared = _common_prefix(wanted, candidate)
    if shared >= 4:
        return round(0.9 * shared / max(len(wanted), len(candidate)), 4)
    if wanted in candidate or candidate in wanted:
        return 0.55
    return 0.0


def score_name(wanted: str, candidate: str) -> float:
    """Similarity of two fund names, 0 when they are different funds.

    A differing share class is disqualifying: 「联接C」 and 「联接A」 are both
    prefix-compatible with a truncated 「联接」 name, but never with each other.
    """
    wanted_class = share_class_of(wanted)
    candidate_class = share_class_of(candidate)
    if wanted_class and candidate_class and wanted_class != candidate_class:
        return 0.0
    return _prefix_score(normalize(wanted), normalize(candidate))


def rank_names(
    wanted: str, directory: list[tuple[str, str]], limit: int = 5, min_score: float = 0.5
) -> list[NameMatch]:
    """Score a whole directory against one name, best first.

    Args:
        wanted: The name as read off the screenshot.
        directory: (code, name) pairs to search.
        limit: How many candidates to return.
        min_score: Anything weaker is noise, not a candidate.
    """
    wanted_clean = (wanted or "").strip()
    if not wanted_clean:
        return []

    matches: list[NameMatch] = []
    for code, name in directory:
        value = score_name(wanted_clean, name)
        if value >= min_score:
            matches.append(NameMatch(fund_code=code, fund_name=name, score=value))
    # Best score first, then the shorter name: 联接C beats 联接C人民币 when both fit.
    matches.sort(key=lambda match: (-match.score, len(match.fund_name), match.fund_code))
    return matches[:limit]


def decide(matches: list[NameMatch], auto_accept: float = 0.95) -> NameMatch | None:
    """The single fund a name resolves to, or None when it must be chosen.

    Candidates are compared per fund, not per spelling: the directory carries the
    register's short name and the synced legal name for the same code on purpose,
    and once both fold to the same form a fund would otherwise be its own runner-up
    and stop matching the day its master row appears. Only a *different* code within
    0.05 is ambiguity — those are share classes, and the difference is real money in
    the wrong place.
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
