"""Local OCR: one screenshot in, text blocks with their boxes out.

The PP-OCR detection and recognition models run on CPU through ONNX Runtime,
so a holdings screenshot never leaves the machine and the same file yields the
same blocks every time. The layout rules downstream are pure geometry, and
they need that stability — a model that occasionally reads a column header as
a holding is not a foundation to cluster rows on.
"""

import asyncio
import time
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.integrations.holdings.ocr_client import OCR_AVAILABLE, RapidOCR


class TextBlock(BaseModel):
    """One run of recognized text and the rectangle it occupied."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def center_x(self) -> float:
        """Horizontal midpoint, the coordinate columns are assigned by."""
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        """Vertical midpoint, the coordinate rows are clustered by."""
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        """Box height in pixels, used to judge how far apart two lines are."""
        return self.y1 - self.y0


class OcrPage(BaseModel):
    """One image: its pixel size plus every block read off it."""

    path: str
    width: float
    height: float
    blocks: list[TextBlock] = Field(default_factory=list)


class OcrUnavailableError(RuntimeError):
    """The optional OCR runtime is not installed in this deployment."""


def _to_blocks(raw: object) -> list[TextBlock]:
    """Convert an engine result into blocks, normalizing quad boxes."""
    texts = getattr(raw, "txts", None)
    boxes = getattr(raw, "boxes", None)
    scores = getattr(raw, "scores", None)
    if texts is None or boxes is None:
        return []

    confidence = list(scores) if scores is not None else [1.0] * len(list(texts))
    blocks: list[TextBlock] = []
    for text, box, score in zip(texts, boxes, confidence, strict=True):
        points = box.tolist() if hasattr(box, "tolist") else list(box)
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        cleaned = str(text).strip()
        if not cleaned:
            continue
        blocks.append(
            TextBlock(
                text=cleaned,
                x0=min(xs),
                y0=min(ys),
                x1=max(xs),
                y1=max(ys),
                score=round(float(score), 4),
            )
        )
    return blocks


class ScreenshotOcr:
    """Lazily-loaded OCR engine, shared for the life of the process."""

    def __init__(self) -> None:
        """Hold the engine unconstructed until the first screenshot arrives."""
        self._engine: RapidOCR | None = None

    @property
    def available(self) -> bool:
        """Whether this deployment can run OCR at all."""
        return OCR_AVAILABLE

    def _engine_or_fail(self) -> RapidOCR:
        """Create the engine on first use (loading the weights costs ~1s)."""
        if not OCR_AVAILABLE or RapidOCR is None:
            raise OcrUnavailableError("ocr_runtime_not_installed")
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

    def _read(self, path: str) -> OcrPage:
        """Blocking OCR call, run off the event loop."""
        with Image.open(path) as image:
            width, height = image.size
        started = time.monotonic()
        page = OcrPage(
            path=path, width=float(width), height=float(height), blocks=_to_blocks(self._engine_or_fail()(path))
        )
        page.blocks.sort(key=lambda block: (block.y0, block.x0))
        logger.info(
            "ocr_page_read",
            image=Path(path).name,
            blocks=len(page.blocks),
            seconds=round(time.monotonic() - started, 2),
        )
        return page

    async def read(self, path: str) -> OcrPage:
        """Recognize one screenshot.

        Raises:
            OcrUnavailableError: the optional runtime is not installed.
        """
        return await asyncio.to_thread(self._read, path)


screenshot_ocr = ScreenshotOcr()
