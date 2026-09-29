"""ScreenshotPositionExtractor: image → structured fields.

Sits between the ScreenshotImportProvider and the OCR engine so the provider
stays business-logic-only (MVP spec 3.7.2 component split): the engine reads
pixels, this turns them into rows, and nothing above it knows which OCR
library is installed.
"""

import asyncio
import hashlib
from pathlib import Path

from app.core.config import settings
from app.core.logging import logger
from app.integrations.holdings.base import RawExtractedPosition
from app.integrations.holdings.fields import to_positions
from app.integrations.holdings.layout import build_layout
from app.integrations.holdings.ocr import OcrUnavailableError, screenshot_ocr
from app.integrations.holdings.rows import read_rows

# ONNX Runtime already spreads one page over its threads; a second page in
# parallel keeps the worker busy without queuing a third copy of the models.
_CONCURRENCY = 2


def image_hash(path: str) -> str:
    """SHA-256 of the file bytes, for dedup across screenshots."""
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


class ScreenshotPositionExtractor:
    """Extracts raw positions from screenshots with local OCR."""

    async def extract(self, image_paths: list[str]) -> tuple[list[RawExtractedPosition], list[str], str | None]:
        """Extract positions from all images.

        Args:
            image_paths: Local temp file paths of uploaded screenshots.

        Returns:
            (positions, image_hashes, error_message). Images that fail to parse
            don't abort the batch — remaining results still return (spec 3.7.2
            multi-screenshot requirements); the first error is reported
            alongside.
        """
        hashes: list[str] = []
        unique: list[str] = []
        seen: set[str] = set()
        for path in image_paths:
            # Hashing reads the whole file: up to 8MB per screenshot, so it
            # must not run on the event loop.
            digest = await asyncio.to_thread(image_hash, path)
            hashes.append(digest)
            if digest in seen:
                logger.info("screenshot_duplicate_skipped", digest=digest)
                continue
            seen.add(digest)
            unique.append(path)

        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def read(path: str) -> tuple[list[RawExtractedPosition], str | None]:
            async with semaphore:
                try:
                    return await self._read_one(path), None
                except OcrUnavailableError:
                    # Every image would fail the same way; say it once, loudly,
                    # instead of a batch of per-file noise.
                    raise
                except Exception as e:
                    logger.warning("screenshot_extraction_failed", path=path, error=str(e))
                    return [], f"{Path(path).name}: {e}"

        results = await asyncio.gather(*(read(path) for path in unique))
        positions = [position for rows, _ in results for position in rows]
        errors = [error for _, error in results if error]

        logger.info(
            "screenshot_extraction_batch_done",
            images=len(image_paths),
            positions=len(positions),
            errors=len(errors),
            max_images=settings.HOLDING_IMPORT_MAX_IMAGES,
        )
        return positions, hashes, "; ".join(errors) if errors else None

    async def _read_one(self, path: str) -> list[RawExtractedPosition]:
        """One screenshot: OCR, then structure → rows → fields.

        Raises:
            OcrUnavailableError: the optional OCR extra is not installed.
        """
        page = await screenshot_ocr.read(path)
        layout = build_layout(page)
        rows = read_rows(page, layout)
        if not rows:
            logger.warning("screenshot_no_rows_detected", image=Path(path).name, blocks=len(page.blocks))
        return to_positions(rows, layout)


screenshot_position_extractor = ScreenshotPositionExtractor()
