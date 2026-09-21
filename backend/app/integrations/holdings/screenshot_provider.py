"""Screenshot import provider: screenshots → resolved, validated draft."""

from app.core.logging import logger
from app.integrations.holdings.base import (
    HoldingImportDraft,
    HoldingImportPayload,
)
from app.integrations.holdings.extractors import screenshot_position_extractor
from app.integrations.holdings.normalizer import (
    dedupe_by_fund,
    normalize_raw_position,
    validate_draft_item,
)
from app.services.fund_service import fund_service


class ScreenshotImportProvider:
    """Parses third-party app screenshots into a pending draft.

    Pipeline per MVP spec 3.7.2:
    extractor → RawExtractedPosition[] → Fund Resolver → Normalizer →
    Validator → HoldingImportDraft. Never writes holdings directly.
    """

    async def parse(self, payload: HoldingImportPayload) -> HoldingImportDraft:
        """Extract, resolve, normalize and validate all screenshot rows."""
        draft = HoldingImportDraft()

        raw_positions, hashes, error = await screenshot_position_extractor.extract(payload.image_paths)
        draft.image_hashes = hashes
        draft.image_count = len(payload.image_paths)
        if error:
            draft.error_message = error

        items = []
        for raw in raw_positions:
            item = normalize_raw_position(raw)
            fund, confidence = await fund_service.resolve_fund(raw.fund_name, raw.fund_code)
            if fund is not None:
                item.matched_fund_code = fund.fund_code
                item.matched_fund_name = fund.fund_name
                item.confidence = min(item.confidence, confidence) if confidence > 0 else confidence
            items.append(validate_draft_item(item))

        draft.items = [validate_draft_item(item) for item in dedupe_by_fund(items)]
        logger.info(
            "screenshot_import_parsed",
            account_id=payload.account_id,
            images=draft.image_count,
            items=len(draft.items),
        )
        return draft
