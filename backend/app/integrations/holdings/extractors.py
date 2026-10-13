"""ScreenshotPositionExtractor：图片 → 结构化字段.

夹在 ScreenshotImportProvider 和 OCR 引擎之间，让 provider 只谈业务逻辑
（MVP spec 3.7.2 的组件拆分）：引擎负责读像素，这里把像素变成一行行持仓，
再往上的代码完全不知道装的是哪个 OCR 库。
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

# ONNX Runtime 算一页时自己就会把计算铺到多个线程上；并行到第二页足够让
# worker 一直有活干，再多只会让模型副本跟着排队，并不会更快。
_CONCURRENCY = 2
_HOLDING_MARKERS = ("持仓", "持有", "份额", "市值", "持有收益", "持仓成本")
_FUND_MARKERS = ("混合", "债券", "股票型", "指数", "联接", "ETF", "LOF", "QDII")
_CHART_MARKERS = ("业绩走势", "净值走势", "走势图", "K线", "日K", "周K", "月K")


class ScreenshotContentError(ValueError):
    """OCR 已运行，但图中没有可导入的持仓内容，错误正文为稳定原因码."""


def image_hash(path: str) -> str:
    """文件字节的 SHA-256，用来在多张截图之间去重."""
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


class ScreenshotPositionExtractor:
    """用本地 OCR 从截图里抽出原始持仓."""

    async def extract(self, image_paths: list[str]) -> tuple[list[RawExtractedPosition], list[str], str | None]:
        """从所有图片里抽出持仓.

        Args:
            image_paths: 上传截图在本机的临时文件路径。

        Returns:
            (positions, image_hashes, error_message)。某张图解析失败不会让整批
            中止——剩下的结果照样返回（spec 3.7.2 的多截图要求），同时把第一条
            错误一并带回来。
        """
        hashes: list[str] = []
        unique: list[str] = []
        seen: set[str] = set()
        for path in image_paths:
            # 算哈希要把整个文件读完：单张截图最大 8MB，所以绝不能放在
            # 事件循环里跑。
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
                    # 引擎缺失时每张都会以同样的方式失败；说一句清楚的重话，
                    # 胜过一堆逐文件的噪音。
                    raise
                except ScreenshotContentError as exc:
                    return [], str(exc)
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
        """一张截图：先 OCR，再按 版面 → 行 → 字段 逐级结构化.

        Raises:
            OcrUnavailableError: 可选的 OCR 附加依赖没装。
        """
        page = await screenshot_ocr.read(path)
        layout = build_layout(page)
        rows = read_rows(page, layout)
        positions = to_positions(rows, layout)
        text = " ".join(block.text for block in page.blocks)
        holding_context = any(marker in text for marker in _HOLDING_MARKERS)
        fund_rows = any(any(marker in (row.fund_name or "") for marker in _FUND_MARKERS) for row in positions)
        holding_values = any(
            any(value is not None for value in (row.market_value, row.shares, row.cost_amount, row.profit_loss))
            for row in positions
        )
        chart_only = not holding_context and any(marker in text for marker in _CHART_MARKERS)
        if positions and not chart_only and (holding_context or fund_rows or holding_values):
            return positions
        if not positions:
            logger.warning("screenshot_no_rows_detected", image=Path(path).name, blocks=len(page.blocks))
        if not page.blocks:
            raise ScreenshotContentError("screenshot_unreadable")
        fund_context = any(marker in text for marker in _FUND_MARKERS)
        if (holding_context or fund_context) and not chart_only:
            raise ScreenshotContentError("no_positions_detected")
        if chart_only or (len(page.blocks) >= 3 and all(block.score >= 0.8 for block in page.blocks)):
            raise ScreenshotContentError("not_holding_screenshot")
        raise ScreenshotContentError("screenshot_unreadable")


screenshot_position_extractor = ScreenshotPositionExtractor()
