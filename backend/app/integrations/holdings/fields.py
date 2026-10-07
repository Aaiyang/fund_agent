"""字段解析：把聚好的一行里的数字变成持仓字段.

一列里常常上下叠着两个数——金额压在昨日收益上面，持有收益压在它自己的收益率
上面——所以一个块算哪个字段，取决于它落在这一行的第几行，而不是它自己的文本。
行的上下两截偶尔会错开几个像素，靠文本认就会把昨日收益当成持有收益，
而这类错误会把一条持仓的价钱悄悄算歪。
"""

import re

from app.core.logging import logger
from app.integrations.holdings.base import RawExtractedPosition
from app.integrations.holdings.layout import PageLayout, Slot
from app.integrations.holdings.ocr import TextBlock
from app.integrations.holdings.rows import HoldingRow

# 负号长什么样取决于字体和这一遍 OCR，前后一共会遇到四种字形。
_MINUS = re.compile(r"^[−–—‐]")
_NOISE = re.compile(r"[¥￥$,,\s]")


def parse_figure(text: str) -> tuple[float | None, bool]:
    """读截图里的一个数字，返回 (数值, 是否带过百分号).

    只要读不出数值就返回 (None, False)——被截断的行只剩半截也算——
    绝不替它凭空造出一个 0。
    """
    raw = _MINUS.sub("-", text.strip())
    percent = raw.rstrip().endswith("%")
    cleaned = _NOISE.sub("", raw.replace("%", ""))
    if not cleaned or cleaned in {"-", "+", "--", "—"}:
        return None, percent
    try:
        return float(cleaned), percent
    except ValueError:
        return None, percent


def _lines(blocks: list[TextBlock], tolerance: float) -> dict[int, list[TextBlock]]:
    """把一行的数值块按上下叠放的行归组，最上面一行编号是 0."""
    ordered = sorted(blocks, key=lambda block: block.center_y)
    lines: list[list[TextBlock]] = []
    for block in ordered:
        if lines and block.center_y - lines[-1][-1].center_y <= tolerance:
            lines[-1].append(block)
        else:
            lines.append([block])
    return {index: group for index, group in enumerate(lines)}


def _slot_of(layout: PageLayout, column_index: int, line: int) -> Slot | None:
    """某一列的第 n 行对应哪个字段."""
    if column_index >= len(layout.columns):
        return None
    column = layout.columns[column_index]
    return column.upper if line == 0 else column.lower


def to_positions(rows: list[HoldingRow], layout: PageLayout) -> list[RawExtractedPosition]:
    """把聚好的行变成抽出的持仓，等着做基金解析."""
    line_tolerance = layout.median_height * 0.6
    positions: list[RawExtractedPosition] = []
    dropped = 0
    for row in rows:
        values: dict[Slot, float] = {}
        scores: list[float] = []
        # 数字该在的位置上有块、却解析不出数值：说明这一行被屏幕截掉了半截，
        # 屏幕上显示的连半个字形都不完整。
        partial = False
        for column_index, column in enumerate(layout.columns):
            if column.upper == "name" or column.upper is None:
                continue
            blocks = row.cells.get(column.upper, [])
            if not blocks:
                continue
            for line, group in _lines(blocks, line_tolerance).items():
                slot = _slot_of(layout, column_index, line)
                if slot is None:
                    continue
                number, percent = parse_figure(group[0].text)
                scores.extend(block.score for block in group)
                if number is None:
                    partial = True
                    continue
                if slot == "profit_loss_rate" and not percent:
                    # 只有收益率这一个数可能给的是小数而不是百分点（% 号丢了），
                    # 这种歧义不去猜。
                    continue
                values[slot] = number

        if partial:
            # 被屏幕截掉半截的行缺了一个数，谁都补不回来；
            # 导入半条持仓比把它留给下一张截图更糟，
            # 所以这种行根本不会进复核页。
            dropped += 1
            continue

        confidence = min(scores) if scores else 0.0
        if row.truncated:
            confidence = min(confidence, 0.7)
        positions.append(
            RawExtractedPosition(
                fund_name=row.name,
                market_value=values.get("market_value"),
                shares=values.get("shares"),
                cost_amount=values.get("cost_amount"),
                average_cost_nav=values.get("average_cost_nav"),
                profit_loss=values.get("profit_loss"),
                profit_loss_rate=values.get("profit_loss_rate"),
                daily_profit_loss=values.get("daily_profit_loss"),
                truncated=row.truncated,
                confidence=round(confidence, 3),
            )
        )

    if dropped:
        logger.info("screenshot_rows_dropped", dropped=dropped, kept=len(positions))
    return positions
