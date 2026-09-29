"""Row clustering: turning a page of loose text blocks into holding rows.

OCR hands back rectangles with no idea what they are. This groups them by
vertical position into rows, keeps the ones that look like a holding (a name
on the left plus at least one figure in a value column) and drops the rest —
the news cards wedged between rows, the share-class chips under a name, and the
bottom navigation bar are all text on the same image and must not become
holdings.
"""

import re
from dataclasses import dataclass, field

from app.integrations.holdings.layout import ColumnBand, PageLayout, Slot
from app.integrations.holdings.ocr import OcrPage, TextBlock

# Words that are page furniture on every fund app: tab strips, sort menus and
# the bottom navigation bar. Matched exactly, because a fund called
# 「持有收益」 would be a name, not chrome — the values here never are.
_CHROME = {
    "全部",
    "偏股",
    "偏债",
    "指数",
    "黄金",
    "全球",
    "我的持有",
    "金额排序",
    "收益率排序",
    "基金市场",
    "机会",
    "自选",
    "持有",
    "行情",
    "交易",
    "资产",
    "我的",
}

# Short labels an app stamps under a fund name. They sit in the name column and
# would otherwise be glued onto the fund's name.
_CHIPS = {
    "金选",
    "指数基金",
    "定投",
    "已开启定投",
    "新品",
    "优选",
    "自选",
    "持有",
    "限购",
    "暂停申购",
    "高风险",
    "中高风险",
    "中低风险",
}

# In-image cards and banners: they span the whole width, so no column owns them.
_CARD = re.compile(r"^(市场解读|热门|快讯|解读|观点|查看|更多)")

_TRUNCATION = ("…", "...", "…...", "..")


@dataclass(frozen=True)
class HoldingRow:
    """One visual row that carries a holding."""

    name: str
    cells: dict[Slot, list[TextBlock]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    truncated: bool = False
    # How far below the header the row sits, kept for ordering and logging.
    top: float = 0.0

    @property
    def figure_count(self) -> int:
        """How many values were read in this row."""
        return sum(len(blocks) for slot, blocks in self.cells.items() if slot != "name")


def _is_chrome(block: TextBlock, header_y: float | None, page_width: float) -> bool:
    """Whether a block is page furniture rather than table content."""
    text = block.text.strip()
    if header_y is not None and block.center_y <= header_y + block.height / 2:
        return True
    if text in _CHROME:
        return True
    if _CARD.match(text):
        return True
    # A line spanning nearly the whole width is a banner, not a table cell.
    return block.x1 - block.x0 > 0.7 * page_width


def _is_chip(block: TextBlock) -> bool:
    """Whether a name-column block is a stamped label rather than part of a name."""
    return block.text.strip() in _CHIPS


def _cluster(blocks: list[TextBlock], median_height: float) -> list[list[TextBlock]]:
    """Group blocks into visual rows by how far apart they sit vertically."""
    if not blocks:
        return []
    ordered = sorted(blocks, key=lambda block: block.center_y)
    gap = max(median_height * 1.4, 40.0)
    rows: list[list[TextBlock]] = [[ordered[0]]]
    for block in ordered[1:]:
        if block.center_y - rows[-1][-1].center_y > gap:
            rows.append([block])
        else:
            rows[-1].append(block)
    return rows


def _name_of(blocks: list[TextBlock]) -> tuple[str, bool]:
    """Join a row's name lines in reading order and report truncation."""
    ordered = sorted(blocks, key=lambda block: (round(block.center_y / 10), block.x0))
    name = "".join(block.text.strip() for block in ordered)
    truncated = any(block.text.strip().endswith(mark) for block in ordered for mark in _TRUNCATION)
    if truncated:
        name = name.rstrip("…. ")
    return name, truncated


def _split_columns(blocks: list[TextBlock], columns: tuple[ColumnBand, ...]) -> dict[ColumnBand, list[TextBlock]]:
    """Assign blocks to columns, preserving left-to-right reading order inside each."""
    spread: dict[ColumnBand, list[TextBlock]] = {}
    for block in blocks:
        column = next((candidate for candidate in columns if candidate.holds(block)), None)
        if column is not None:
            spread.setdefault(column, []).append(block)
    return {column: sorted(items, key=lambda block: block.center_y) for column, items in spread.items()}


def read_rows(page: OcrPage, layout: PageLayout) -> list[HoldingRow]:
    """Extract the holding rows a screenshot shows, top to bottom."""
    content = [block for block in page.blocks if not _is_chrome(block, layout.header_y, page.width)]
    rows: list[HoldingRow] = []
    for cluster in _cluster(content, layout.median_height):
        spread = _split_columns(cluster, layout.columns)
        name_column = next((column for column in spread if column.upper == "name"), None)
        value_columns = [column for column in spread if column.upper != "name"]
        if name_column is None or not value_columns:
            continue

        name_blocks = spread[name_column]
        lowest_figure = max(
            (block.center_y for column in value_columns for block in spread[column]),
            default=0.0,
        )
        # A name-column line that sits below every figure is a chip: apps stamp
        # 金选/定投 there, and gluing it on produces a fund that does not exist.
        kept = [
            block
            for block in name_blocks
            if not _is_chip(block)
            and (lowest_figure == 0.0 or block.center_y <= lowest_figure + layout.median_height * 0.5)
        ]
        if not kept:
            continue

        cells: dict[Slot, list[TextBlock]] = {}
        for column in value_columns:
            if column.upper is None:
                continue
            cells.setdefault(column.upper, []).extend(spread[column])

        chips = [block for block in name_blocks if block not in kept]
        name, truncated = _name_of(kept)
        rows.append(
            HoldingRow(
                name=name,
                cells=cells,
                tags=tuple(block.text.strip() for block in chips),
                truncated=truncated,
                top=min(block.y0 for block in cluster),
            )
        )
    return sorted(rows, key=lambda row: row.top)
