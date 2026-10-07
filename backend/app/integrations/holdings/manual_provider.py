"""手动录入导入 provider：把手填的持仓行转成草稿."""

from app.core.logging import logger
from app.integrations.holdings.base import (
    HoldingImportDraft,
    HoldingImportPayload,
)
from app.integrations.holdings.normalizer import validate_draft_item
from app.services.fund_service import fund_service


class ManualImportProvider:
    """解析手动录入的持仓（完全不碰 OCR）.

    手动输入在结构上默认可信（confidence 1.0），但仍要和别的导入一样走基金解析
    与校验——手动行同样进的是那条"先确认、后落库"的流程（MVP spec 3.7.1）。
    """

    async def parse(self, payload: HoldingImportPayload) -> HoldingImportDraft:
        """把每条手动行解析成标准基金，并做校验."""
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
