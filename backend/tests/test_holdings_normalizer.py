"""Import normalization/validation is pure and must stay unit-tested (spec 3.7)."""

from app.integrations.holdings.base import DraftPositionItem, RawExtractedPosition
from app.integrations.holdings.normalizer import (
    LOW_CONFIDENCE_THRESHOLD,
    dedupe_by_fund,
    normalize_raw_position,
    parse_amount,
    parse_percent,
    validate_draft_item,
)


def _item(**overrides: object) -> DraftPositionItem:
    """A valid draft row with optional field overrides."""
    payload: dict = {
        "raw_fund_name": "华泰柏瑞质量成长混合C",
        "matched_fund_code": "011452",
        "market_value": 881.99,
        "profit_loss": -137.20,
        "confidence": 0.96,
    }
    payload.update(overrides)
    return DraftPositionItem(**payload)  # pyright: ignore[reportArgumentType]


class TestParsers:
    def test_amount_strips_currency_and_separators(self) -> None:
        assert parse_amount("¥1,234.56") == 1234.56
        assert parse_amount("  881.99 ") == 881.99
        assert parse_amount("--") is None
        assert parse_amount(None) is None
        assert parse_amount(12.5) == 12.5

    def test_percent_keeps_percent_units(self) -> None:
        assert parse_percent("-13.46%") == -13.46
        assert parse_percent("2.2") == 2.2
        assert parse_percent("--") is None


class TestNormalizeRawPosition:
    def test_trims_name_and_keeps_missing_fields_none(self) -> None:
        draft = normalize_raw_position(RawExtractedPosition(fund_name="  示例基金  ", market_value=None))
        assert draft.raw_fund_name == "示例基金"
        assert draft.market_value is None
        assert draft.confidence == 0.5

    def test_blank_name_becomes_none(self) -> None:
        assert normalize_raw_position(RawExtractedPosition(fund_name="   ")).raw_fund_name is None


class TestValidateDraftItem:
    def test_clean_row_is_valid(self) -> None:
        validated = validate_draft_item(_item())
        assert (validated.validation_status, validated.validation_issues) == ("valid", [])

    def test_unresolved_fund_is_blocking(self) -> None:
        validated = validate_draft_item(_item(matched_fund_code=None))
        assert validated.validation_status == "error"
        assert "fund_unresolved" in validated.validation_issues

    def test_missing_value_and_shares_is_blocking(self) -> None:
        validated = validate_draft_item(_item(market_value=None, shares=None))
        assert validated.validation_status == "error"
        assert "missing_market_value_and_shares" in validated.validation_issues

    def test_only_shares_is_acceptable_partial_snapshot(self) -> None:
        """Spec 3.7.1: partial snapshots are allowed, not invented away."""
        validated = validate_draft_item(_item(market_value=None, shares=295.1))
        assert validated.validation_status == "valid"

    def test_low_confidence_is_a_warning(self) -> None:
        validated = validate_draft_item(_item(confidence=LOW_CONFIDENCE_THRESHOLD - 0.1))
        assert validated.validation_status == "warning"
        assert "low_confidence" in validated.validation_issues

    def test_inconsistent_profit_and_absurd_rate_are_flagged(self) -> None:
        validated = validate_draft_item(_item(profit_loss=-99999.0, profit_loss_rate=900.0))
        assert "profit_loss_inconsistent_with_value" in validated.validation_issues
        assert "profit_loss_rate_out_of_range" in validated.validation_issues
        assert validated.validation_status == "warning"


class TestDedupeByFund:
    def test_merges_cross_screenshot_duplicates_filling_missing_fields(self) -> None:
        merged = dedupe_by_fund(
            [
                _item(market_value=881.99, shares=None, cost_amount=None),
                _item(market_value=881.99, shares=295.1, cost_amount=1019.19),
            ]
        )
        assert len(merged) == 1
        assert merged[0].shares == 295.1
        assert merged[0].cost_amount == 1019.19

    def test_conflicting_values_on_the_same_fund_warn(self) -> None:
        merged = dedupe_by_fund([_item(market_value=881.99), _item(market_value=1000.0)])
        assert len(merged) == 1
        assert merged[0].validation_status == "warning"
        assert "duplicate_fund_different_values" in merged[0].validation_issues

    def test_rows_without_any_key_are_kept_separately(self) -> None:
        anonymous = [
            _item(matched_fund_code=None, raw_fund_name=None),
            _item(matched_fund_code=None, raw_fund_name=None),
        ]
        assert len(dedupe_by_fund(anonymous)) == 2
