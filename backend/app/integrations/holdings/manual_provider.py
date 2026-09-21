"""Manual import provider: converts hand-entered rows into a draft."""

from app.core.logging import logger
from app.integrations.holdings.base import (
    HoldingImportDraft,
    HoldingImportPayload,
)
from app.integrations.holdings.normalizer import validate_draft_item
from app.services.fund_service import fund_service


class ManualImportProvider:
    """Parses manual holding entries (no OCR involved).

    Manual input is structurally trusted (confidence 1.0) but still flows
    through fund resolution and validation like any other import — manual
    rows also land in the same confirm-before-write flow (MVP spec 3.7.1).
    """

    async def parse(self, payload: HoldingImportPayload) -> HoldingImportDraft:
        """Resolve each manual row to a standard fund and validate it."""
        from app.integrations.holdings.base import DraftPositionItem

        draft = HoldingImportDraft()
        for row in payload.manual_positions:
            fund, confidence = await fund_service.resolve_fund(row.fund_name, row.fund_code)
            item = DraftPositionItem(
                raw_fund_name=row.fund_name,
                matched_fund_code=fund.fund_code if fund else None,
                matched_fund_name=fund.fund_name if fund else None,
                market_value=row.market_value,
                shares=row.shares,
                cost_amount=row.cost_amount,
                average_cost_nav=row.average_cost_nav,
                profit_loss=row.profit_loss,
                profit_loss_rate=row.profit_loss_rate,
                confidence=confidence if fund else 0.3,
            )
            draft.items.append(validate_draft_item(item))
        logger.info(
            "manual_import_parsed",
            account_id=payload.account_id,
            rows=len(draft.items),
        )
        return draft
