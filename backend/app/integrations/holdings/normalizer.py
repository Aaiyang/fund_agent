"""Normalization and validation of extracted/import positions.

Pure functions — unit-testable without any I/O (MVP spec 3.7: Normalizer
unifies amount/percent/date formats; Validator flags anomalies).
"""

import re

from app.integrations.holdings.base import DraftPositionItem, RawExtractedPosition

_AMOUNT = re.compile(r"[¥￥$,，\s]")
_PERCENT = re.compile(r"%\s*$")

# Below this, a fund match needs explicit human confirmation (spec 3.7.2)
LOW_CONFIDENCE_THRESHOLD = 0.6


def parse_amount(value: str | float | int | None) -> float | None:
    """Normalize money-like input ('¥1,234.56' / '1234.56' / 1234.56)."""
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
    """Normalize percent-like input ('-13.46%' → -13.46, stays in % units)."""
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
    """Convert a raw extracted row into a draft item (no fund resolution)."""
    return DraftPositionItem(
        raw_fund_name=(raw.fund_name or "").strip() or None,
        market_value=raw.market_value,
        shares=raw.shares,
        cost_amount=raw.cost_amount,
        average_cost_nav=raw.average_cost_nav,
        profit_loss=raw.profit_loss,
        profit_loss_rate=raw.profit_loss_rate,
        truncated=raw.truncated,
        partial=raw.partial,
        confidence=raw.confidence,
    )


def _sign(value: float) -> int:
    """-1 / 0 / 1, so a pair of figures can be compared without float maths."""
    return (value > 0) - (value < 0)


def validate_draft_item(item: DraftPositionItem) -> DraftPositionItem:
    """Flag anomalies: unknown fund, missing value, suspicious ranges, dupes.

    Validation status values: valid / warning / error. Error rows can still
    be user-corrected on the confirm page; only 'valid' import unedited.
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
    # Screenshot-specific: a clipped name is several funds until he picks one,
    # and a row whose columns filled unevenly was cut off by the screen.
    if item.truncated:
        issues.append("fund_name_truncated")
    if item.partial:
        issues.append("row_incomplete")
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
    """Merge duplicate funds across screenshots, keeping the richer row.

    Later rows fill fields missing from the first occurrence; a differing
    market_value on the same fund is flagged as a warning.
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
