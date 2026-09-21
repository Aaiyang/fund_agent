"""ScreenshotPositionExtractor: image → structured fields.

Sits between the ScreenshotImportProvider and the Vision/OCR adapter so the
provider stays business-logic-only (MVP spec 3.7.2 component split).
"""

import hashlib
from datetime import date

from app.core.config import settings
from app.core.logging import logger
from app.integrations.fund_data.normalizer import to_date, to_float
from app.integrations.holdings.base import RawExtractedPosition
from app.integrations.holdings.vision_adapter import vision_adapter


def image_hash(path: str) -> str:
    """SHA-256 of the file bytes, for dedup across screenshots."""
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


class ScreenshotPositionExtractor:
    """Extracts raw positions from screenshots via the vision adapter."""

    async def extract(self, image_paths: list[str]) -> tuple[list[RawExtractedPosition], list[str], str | None]:
        """Extract positions from all images.

        Args:
            image_paths: Local temp file paths of uploaded screenshots.

        Returns:
            (positions, image_hashes, error_message). Images that fail to
            parse don't abort the batch — remaining results still return
            (spec 3.7.2 multi-screenshot requirements); the first error is
            reported alongside.
        """
        positions: list[RawExtractedPosition] = []
        hashes: list[str] = []
        errors: list[str] = []
        seen_hashes: set[str] = set()

        for path in image_paths:
            digest = image_hash(path)
            hashes.append(digest)
            if digest in seen_hashes:
                logger.info("screenshot_duplicate_skipped", digest=digest)
                continue
            seen_hashes.add(digest)

            try:
                rows = await vision_adapter.extract_positions(path)
            except Exception as e:
                logger.warning("screenshot_extraction_failed", path=path, error=str(e))
                errors.append(f"{path}: {e}")
                continue

            for row in rows:
                positions.append(
                    RawExtractedPosition(
                        fund_name=str(row.get("fund_name") or "").strip() or None,
                        fund_code=str(row.get("fund_code") or "").strip() or None,
                        market_value=to_float(row.get("market_value")),
                        shares=to_float(row.get("shares")),
                        cost_amount=to_float(row.get("cost_amount")),
                        average_cost_nav=to_float(row.get("average_cost_nav")),
                        profit_loss=to_float(row.get("profit_loss")),
                        profit_loss_rate=to_float(row.get("profit_loss_rate")),
                        daily_profit_loss=to_float(row.get("daily_profit_loss")),
                        data_date=to_date(row.get("data_date")) or date.today(),
                        confidence=to_float(row.get("confidence")) or 0.5,
                    )
                )

        error_message = "; ".join(errors) if errors else None
        logger.info(
            "screenshot_extraction_batch_done",
            images=len(image_paths),
            positions=len(positions),
            errors=len(errors),
            max_images=settings.HOLDING_IMPORT_MAX_IMAGES,
        )
        return positions, hashes, error_message


screenshot_position_extractor = ScreenshotPositionExtractor()
