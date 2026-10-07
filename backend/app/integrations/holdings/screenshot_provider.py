"""截图导入 provider：截图 → 解析完、校验完的草稿."""

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
    """把第三方 App 的截图解析成一份待确认草稿.

    MVP spec 3.7.2 规定的流水线：
    抽取（extractor）→ RawExtractedPosition[] → 基金解析（Fund Resolver）→ 归一化（Normalizer）
    → 校验（Validator）→ HoldingImportDraft。绝不绕过确认直接写持仓。
    """

    async def parse(self, payload: HoldingImportPayload) -> HoldingImportDraft:
        """对所有截图行做抽取、解析、归一化和校验."""
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
