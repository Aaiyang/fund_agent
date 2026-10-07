"""本地 OCR：进来一张截图，出去带方框的文本块.

PP-OCR 的检测与识别模型通过 ONNX Runtime 跑在 CPU 上，所以持仓截图从不出这台
机器，而且同一个文件每次都给出一样的块。下游的版面规则是纯几何，正需要这份
稳定——一个偶尔把列表头读成持仓的模型，当不了按行聚类的地基。
"""

import asyncio
import time
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.integrations.holdings.ocr_client import OCR_AVAILABLE, RapidOCR


class TextBlock(BaseModel):
    """一段被识别出来的文字，以及它占住的矩形框."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def center_x(self) -> float:
        """水平中点——把块归到哪一列，看的就是这个坐标."""
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        """垂直中点——把块聚成哪一行，看的就是这个坐标."""
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        """框高（像素），用来判断两行隔得有多远."""
        return self.y1 - self.y0


class OcrPage(BaseModel):
    """一张图片：像素尺寸，加上从它上面读出的所有块."""

    path: str
    width: float
    height: float
    blocks: list[TextBlock] = Field(default_factory=list)


class OcrUnavailableError(RuntimeError):
    """这个部署没装可选的 OCR 运行时."""


def _to_blocks(raw: object) -> list[TextBlock]:
    """把引擎的返回结果转成块，顺手把四点框归一成外接矩形."""
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
    """惰性加载的 OCR 引擎，整个进程共用一个实例."""

    def __init__(self) -> None:
        """第一张截图到来之前，先把引擎搁着不构造."""
        self._engine: RapidOCR | None = None

    @property
    def available(self) -> bool:
        """这个部署到底能不能跑 OCR."""
        return OCR_AVAILABLE

    def _engine_or_fail(self) -> RapidOCR:
        """首次使用时才建引擎（加载权重大约要花 1s）."""
        if not OCR_AVAILABLE or RapidOCR is None:
            raise OcrUnavailableError("ocr_runtime_not_installed")
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

    def _read(self, path: str) -> OcrPage:
        """会阻塞的 OCR 调用，要放到事件循环之外去跑."""
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
        """识别一张截图.

        Raises:
            OcrUnavailableError: 可选的 OCR 运行时没装。
        """
        return await asyncio.to_thread(self._read, path)


screenshot_ocr = ScreenshotOcr()
