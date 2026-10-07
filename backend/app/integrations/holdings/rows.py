"""行聚类：把一整页散落的文本块变成一行行持仓.

OCR 交回来的只是一堆矩形，并不知道自己是什么。这里按垂直位置把它们归成行，
留下看着像持仓的那些（左边一个名称，加上数值列里至少一个数字），其余全丢掉——
夹在行间的资讯卡片、名称下面的份额类别标签、底部导航栏，都是同一张图上的文字，
不能当成持仓。
"""

import re
from dataclasses import dataclass, field

from app.integrations.holdings.layout import ColumnBand, PageLayout, Slot
from app.integrations.holdings.ocr import OcrPage, TextBlock

# 每家基金 App 页面上都跑不掉的固定文字：标签条、排序菜单、底部导航栏。
# 这里按整串精确匹配，因为一只真叫「持有收益」的基金那是在报名字，不是页面
# 装饰——而集合里这些值永远只是装饰。
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

# App 盖在基金名称下面的短标签。它们就落在名称列里，
# 不加区分就会被粘到基金名称上去。
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

# 图里的卡片和横幅：它们横贯整个宽度，所以不归任何一列管。
_CARD = re.compile(r"^(市场解读|热门|快讯|解读|观点|查看|更多)")

_TRUNCATION = ("…", "...", "…...", "..")


@dataclass(frozen=True)
class HoldingRow:
    """视觉上的完整一行，里面装着一条持仓."""

    name: str
    cells: dict[Slot, list[TextBlock]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    truncated: bool = False
    # 这一行比表头低多少，留着供排序和打日志用。
    top: float = 0.0

    @property
    def figure_count(self) -> int:
        """这一行里读出了多少个数值."""
        return sum(len(blocks) for slot, blocks in self.cells.items() if slot != "name")


def _is_chrome(block: TextBlock, header_y: float | None, page_width: float) -> bool:
    """这个块是页面装饰，还是表格内容."""
    text = block.text.strip()
    if header_y is not None and block.center_y <= header_y + block.height / 2:
        return True
    if text in _CHROME:
        return True
    if _CARD.match(text):
        return True
    # 横贯几乎整个宽度的那条线是横幅，不是表格单元。
    return block.x1 - block.x0 > 0.7 * page_width


def _is_chip(block: TextBlock) -> bool:
    """名称列里的这个块是被盖上的标签，还是名称本身的一部分."""
    return block.text.strip() in _CHIPS


def _cluster(blocks: list[TextBlock], median_height: float) -> list[list[TextBlock]]:
    """按块在垂直方向上隔得有多远，把它们归成视觉上的行."""
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
    """按阅读顺序把一行的名称各行拼起来，同时报告有没有被截断."""
    ordered = sorted(blocks, key=lambda block: (round(block.center_y / 10), block.x0))
    name = "".join(block.text.strip() for block in ordered)
    truncated = any(block.text.strip().endswith(mark) for block in ordered for mark in _TRUNCATION)
    if truncated:
        name = name.rstrip("…. ")
    return name, truncated


def _split_columns(blocks: list[TextBlock], columns: tuple[ColumnBand, ...]) -> dict[ColumnBand, list[TextBlock]]:
    """把块分配进各列，列内保持从左到右的阅读顺序."""
    spread: dict[ColumnBand, list[TextBlock]] = {}
    for block in blocks:
        column = next((candidate for candidate in columns if candidate.holds(block)), None)
        if column is not None:
            spread.setdefault(column, []).append(block)
    return {column: sorted(items, key=lambda block: block.center_y) for column, items in spread.items()}


def read_rows(page: OcrPage, layout: PageLayout) -> list[HoldingRow]:
    """抽出截图上显示的持仓行，从上往下."""
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
        # 名称列里压在每一个数字下面的那一行是标签：App 会把 金选/定投 盖在那里，
        # 粘上去就拼出一只根本不存在的基金。
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
