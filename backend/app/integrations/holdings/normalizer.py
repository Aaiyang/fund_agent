"""抽取结果与导入持仓的归一化、校验.

都是纯函数——不做任何 I/O 也能单测（MVP spec 3.7：Normalizer 把金额/百分比/日期
格式统一，Validator 把异常标出来）。
"""

import re

from app.integrations.holdings.base import DraftPositionItem, RawExtractedPosition

_AMOUNT = re.compile(r"[¥￥$,，\s]")
_PERCENT = re.compile(r"%\s*$")

# 匹配分低于这个值，就必须由用户显式确认（spec 3.7.2）
LOW_CONFIDENCE_THRESHOLD = 0.6


def parse_amount(value: str | float | int | None) -> float | None:
    """把金额类的输入归一化（'¥1,234.56' / '1234.56' / 1234.56）."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _AMOUNT.sub("", str(value))
    if not text or text in {"--", "-", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_percent(value: str | float | int | None) -> float | None:
    """把百分比类的输入归一化（'-13.46%' → -13.46，仍按 % 计）."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _PERCENT.sub("", str(value).strip())
    if not text or text in {"--", "-", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_raw_position(raw: RawExtractedPosition) -> DraftPositionItem:
    """把抽出的一条原始行转成草稿条目（不做基金解析）."""
    return DraftPositionItem(
        raw_fund_name=(raw.fund_name or "").strip() or None,
        market_value=raw.market_value,
        shares=raw.shares,
        cost_amount=raw.cost_amount,
        average_cost_nav=raw.average_cost_nav,
        profit_loss=raw.profit_loss,
        profit_loss_rate=raw.profit_loss_rate,
        truncated=raw.truncated,
        confidence=raw.confidence,
    )


def _sign(value: float) -> int:
    """给出 -1 / 0 / 1，这样比较两个数同号不用做浮点运算."""
    return (value > 0) - (value < 0)


def validate_draft_item(item: DraftPositionItem) -> DraftPositionItem:
    """标出异常：基金没认出来、数值缺失、量级可疑、重复.

    validation_status 取值：valid / warning / error。error 行仍然可以在确认页上
    由用户改对；只有 'valid' 的行会不加修改地直接导入。
    """
    issues: list[str] = []

    if not item.matched_fund_code:
        issues.append("fund_unresolved")
    if item.market_value is None and item.shares is None:
        issues.append("missing_market_value_and_shares")
    if item.market_value is not None and item.market_value > 1_000_000_000:
        issues.append("market_value_suspiciously_large")
    if item.profit_loss is not None and item.market_value is not None:
        if abs(item.profit_loss) > item.market_value * 10:
            issues.append("profit_loss_inconsistent_with_value")
    if item.profit_loss_rate is not None and abs(item.profit_loss_rate) > 500:
        issues.append("profit_loss_rate_out_of_range")
    if item.confidence < LOW_CONFIDENCE_THRESHOLD:
        issues.append("low_confidence")
    # 截图特有的情况：名称被截断时它还可能指着好几只基金，要等用户选定一只。
    # 被屏幕截掉半截的行根本到不了这里——解析器直接把它丢了，因为缺的那个数
    # 本就不该由用户来补。
    if item.truncated:
        issues.append("fund_name_truncated")
    if item.profit_loss is not None and item.profit_loss_rate is not None:
        if _sign(item.profit_loss) != _sign(item.profit_loss_rate) and 0 not in (
            item.profit_loss,
            item.profit_loss_rate,
        ):
            issues.append("profit_and_rate_disagree")

    blocking = {"fund_unresolved", "missing_market_value_and_shares"}
    item.validation_issues = issues
    item.validation_status = "error" if blocking & set(issues) else ("warning" if issues else "valid")
    return item


def dedupe_by_fund(items: list[DraftPositionItem]) -> list[DraftPositionItem]:
    """把多张截图里重复的基金并成一条，留下信息更全的那行.

    后面的行用来补第一次出现时缺的字段；同一只基金上市值对不上，就标成 warning。
    """
    merged: dict[str, DraftPositionItem] = {}
    unnamed: list[DraftPositionItem] = []
    for item in items:
        key = item.matched_fund_code or (item.raw_fund_name or "")
        if not key:
            unnamed.append(item)
            continue
        if key not in merged:
            merged[key] = item.model_copy()
            continue
        kept = merged[key]
        if (
            item.market_value is not None
            and kept.market_value is not None
            and abs(item.market_value - kept.market_value) > 0.01
        ):
            kept.validation_issues.append("duplicate_fund_different_values")
            kept.validation_status = "warning"
        for field in (
            "shares",
            "cost_amount",
            "average_cost_nav",
            "profit_loss",
            "profit_loss_rate",
            "matched_fund_code",
            "matched_fund_name",
        ):
            if getattr(kept, field) is None and getattr(item, field) is not None:
                setattr(kept, field, getattr(item, field))
    return list(merged.values()) + unnamed
