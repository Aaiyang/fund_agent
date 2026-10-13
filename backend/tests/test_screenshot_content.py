"""验证截图内容分类、多图片部分失败，不依赖真实 OCR 模型或网络."""

from unittest.mock import AsyncMock

import pytest

from app.integrations.holdings.extractors import ScreenshotContentError, ScreenshotPositionExtractor, screenshot_ocr
from app.integrations.holdings.ocr import OcrPage, TextBlock


def block(text, x, y, width=150, score=0.99):
    return TextBlock(text=text, x0=x, y0=y, x1=x + width, y1=y + 54, score=score)


def page(blocks):
    return OcrPage(path="fixture.png", width=1200, height=2670, blocks=blocks)


def holdings_page(*, header=True):
    blocks = [
        block("德邦鑫星价值灵活配置混合C", 72, 850, 400),
        block("846.07", 620, 854),
        block("-20.87", 620, 908),
        block("-21.46", 976, 852),
        block("-2.80%", 976, 910),
    ]
    if header:
        blocks = [
            block("名称", 72, 645, 95),
            block("金额/昨日收益", 520, 650, 255),
            block("持有收益/率", 908, 647, 221),
            *blocks,
        ]
    return page(blocks)


async def test_holding_list_is_accepted(monkeypatch):
    monkeypatch.setattr(screenshot_ocr, "read", AsyncMock(return_value=holdings_page()))
    rows = await ScreenshotPositionExtractor()._read_one("fixture.png")
    assert len(rows) == 1 and rows[0].fund_name == "德邦鑫星价值灵活配置混合C"


@pytest.mark.parametrize(
    "blocks,reason",
    [
        ([], "screenshot_unreadable"),
        ([block("模糊字", 72, 800, score=0.3)], "screenshot_unreadable"),
        ([block("基金持仓", 72, 800)], "no_positions_detected"),
        (holdings_page(header=False).blocks, "no_positions_detected"),
        ([block("今日新闻", 72, 800), block("天气晴朗", 72, 950), block("北京", 72, 1100)], "not_holding_screenshot"),
        ([block("业绩走势", 72, 800), block("近一年", 72, 950)], "not_holding_screenshot"),
        ([block("净值走势", 72, 650), *holdings_page(header=False).blocks], "not_holding_screenshot"),
    ],
)
async def test_non_holdings_and_unreadable_images_have_distinct_reasons(monkeypatch, blocks, reason):
    monkeypatch.setattr(screenshot_ocr, "read", AsyncMock(return_value=page(blocks)))
    with pytest.raises(ScreenshotContentError, match=reason):
        await ScreenshotPositionExtractor()._read_one("fixture.png")


async def test_partial_batch_keeps_good_image_and_reports_wrong_image(monkeypatch, tmp_path):
    good, wrong = tmp_path / "good.png", tmp_path / "wrong.png"
    good.write_bytes(b"good-image")
    wrong.write_bytes(b"wrong-image")

    async def read(path):
        return holdings_page() if path == str(good) else page([block("业绩走势", 72, 800)])

    monkeypatch.setattr(screenshot_ocr, "read", read)
    rows, hashes, error = await ScreenshotPositionExtractor().extract([str(good), str(wrong), str(good)])
    assert len(rows) == 1 and len(hashes) == 3 and hashes[0] == hashes[2]
    assert error == "not_holding_screenshot"
