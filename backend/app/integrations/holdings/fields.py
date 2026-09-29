"""Field parsing: a clustered row's figures become holding fields.

Two figures stack inside one column — 金额 above 昨日收益, 持有收益 above its
rate — so a block's field is decided by which *line* of the row it sits on, not
by its own text. That keeps 昨日收益 out of 持有收益 when a row's lines drift a
few pixels apart, which is the mistake that silently misprices a holding.
"""

import re

from app.integrations.holdings.base import RawExtractedPosition
from app.integrations.holdings.layout import PageLayout, Slot
from app.integrations.holdings.ocr import TextBlock
from app.integrations.holdings.rows import HoldingRow

# Minus arrives as four different glyphs depending on the font and the OCR pass.
_MINUS = re.compile(r"^[−–—‐]")
_NOISE = re.compile(r"[¥￥$,,\s]")


def parse_figure(text: str) -> tuple[float | None, bool]:
    """Read a screenshot number, returning (value, whether it carried a % sign).

    Returns (None, False) for anything that is not a figure — a clipped row's
    half-read line included — rather than inventing a zero.
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
    """Group a row's value blocks into stacked lines, top line = 0."""
    ordered = sorted(blocks, key=lambda block: block.center_y)
    lines: list[list[TextBlock]] = []
    for block in ordered:
        if lines and block.center_y - lines[-1][-1].center_y <= tolerance:
            lines[-1].append(block)
        else:
            lines.append([block])
    return {index: group for index, group in enumerate(lines)}


def _slot_of(layout: PageLayout, column_index: int, line: int) -> Slot | None:
    """Which field a column's nth line is."""
    if column_index >= len(layout.columns):
        return None
    column = layout.columns[column_index]
    return column.upper if line == 0 else column.lower


def to_positions(rows: list[HoldingRow], layout: PageLayout) -> list[RawExtractedPosition]:
    """Turn clustered rows into extracted positions, ready for resolution."""
    line_tolerance = layout.median_height * 0.6
    positions: list[RawExtractedPosition] = []
    for row in rows:
        values: dict[Slot, float] = {}
        scores: list[float] = []
        # A block that sits where a figure belongs but will not parse: the row
        # was cut off mid-height, so half a glyph is all the screen showed.
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
                    # A rate without its % sign is the one figure that can be a
                    # fraction instead of percentage points; refuse to guess.
                    continue
                values[slot] = number

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
                partial=partial,
                confidence=round(confidence, 3),
            )
        )
    return positions
