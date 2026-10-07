"""版面结构：每一列是什么意思，表格从哪里开始.

持仓截图就是一张表，而这张表一般会自己印出表头——「金额/昨日收益」压在一对数字
上面，「持有收益/率」压在另一对上。所以先读表头、照表头给列命名，而不是给每家
App 硬编码一套布局；正是这一点让同一份解析器既能处理支付宝，也能处理任何长得
像它的界面。

截图没带表头时，列就保持无名：把某个金额列认定成市值而不是持仓成本，本质是在
猜，而猜错的市值就是一条落进流水的错误持仓。这些行照样会送到复核页，只是要
打上标记。
"""

from dataclasses import dataclass, field
from typing import Literal

from app.integrations.holdings.ocr import OcrPage, TextBlock

# 截图里一列可能承载的金额字段。`name` 是基金名称那一列。
Slot = Literal[
    "name",
    "market_value",
    "shares",
    "cost_amount",
    "average_cost_nav",
    "profit_loss",
    "profit_loss_rate",
    "daily_profit_loss",
]

# 表头片段 → 字段。按顺序逐个匹配，所以更长、更具体的片段要排在前面：
# 「昨日收益」不能被认成「收益」。
_CAPTION_FRAGMENTS: tuple[tuple[str, Slot], ...] = (
    ("昨日收益", "daily_profit_loss"),
    ("当日收益", "daily_profit_loss"),
    ("日收益", "daily_profit_loss"),
    ("持有收益", "profit_loss"),
    ("累计收益", "profit_loss"),
    ("收益率", "profit_loss_rate"),
    # 表头缩写很随意：「持有收益/率」把下面那个数叫作 率。
    ("收益", "profit_loss"),
    ("率", "profit_loss_rate"),
    ("持有金额", "market_value"),
    ("持仓金额", "market_value"),
    ("最新市值", "market_value"),
    ("市值", "market_value"),
    ("金额", "market_value"),
    ("持仓成本净值", "average_cost_nav"),
    ("成本净值", "average_cost_nav"),
    ("成本价", "average_cost_nav"),
    ("持仓成本", "cost_amount"),
    ("成本", "cost_amount"),
    ("份额", "shares"),
    ("单位净值", "average_cost_nav"),
    ("净值", "average_cost_nav"),
    ("基金名称", "name"),
    ("产品名称", "name"),
    ("名称", "name"),
)

# 一句表头下面叠着两个数：「金额/昨日收益」就是这种。
_UPPER_FOR: dict[Slot, Slot | None] = {
    "market_value": "daily_profit_loss",
    "profit_loss": "profit_loss_rate",
    "cost_amount": "average_cost_nav",
}


@dataclass(frozen=True)
class ColumnBand:
    """截图上的一道竖向切片，以及它承载的字段."""

    x0: float
    x1: float
    upper: Slot | None = None
    lower: Slot | None = None
    caption: str | None = None

    def holds(self, block: TextBlock) -> bool:
        """按水平中心点判断一个块是否落在这一列."""
        return self.x0 <= block.center_x < self.x1


@dataclass(frozen=True)
class PageLayout:
    """一张截图解析出来的骨架."""

    columns: tuple[ColumnBand, ...]
    header_y: float | None = None
    named: bool = True
    median_height: float = 20.0
    dropped: tuple[str, ...] = field(default_factory=tuple)

    def column_for(self, block: TextBlock) -> ColumnBand | None:
        """这个块落在哪一列，落不进就返回 None."""
        return next((column for column in self.columns if column.holds(block)), None)

    def slot_for(self, block: TextBlock, line: int) -> Slot | None:
        """给出块在列内的位置后，判断它算哪个字段."""
        column = self.column_for(block)
        if column is None:
            return None
        return column.upper if line <= 0 else column.lower


def parse_caption(text: str) -> tuple[Slot | None, Slot | None]:
    """把一句表头映射成该列的字段，上面的数排在前面.

    「金额/昨日收益」 → (market_value, daily_profit_loss)；
    「持有收益/率」 → (profit_loss, profit_loss_rate)。
    """
    slots: list[Slot] = []
    for part in text.replace("（", "(").replace("）", ")").split("/"):
        fragment = part.strip()
        if not fragment:
            continue
        matched: Slot | None = next((slot for needle, slot in _CAPTION_FRAGMENTS if needle in fragment), None)
        if matched is None:
            return None, None
        if matched not in slots:
            slots.append(matched)

    if not slots:
        return None, None
    if len(slots) == 1:
        upper = slots[0]
        return upper, _UPPER_FOR.get(upper)
    return slots[0], slots[1]


def _is_caption(block: TextBlock) -> bool:
    """这个块读起来像表头，而不像一条持仓."""
    return block.text.strip() in {"名称", "基金名称", "产品名称"} or "/" in block.text


def find_header(blocks: list[TextBlock]) -> list[TextBlock]:
    """表头行：同一行水平线上挤着两个及以上像表头的块.

    截图根本没有表头可读时返回 []——有的 App 把列名放在筛选条里，把筛选条误当
    表头，会把它下面每一列的语义都改错。
    """
    lines: dict[int, list[TextBlock]] = {}
    for block in blocks:
        if not _is_caption(block) or len(block.text) > 14:
            continue
        lines.setdefault(round(block.center_y / 12), []).append(block)

    best = max(lines.values(), key=len) if lines else []
    named = [block for block in best if parse_caption(block.text)[0] is not None]
    return sorted(named, key=lambda block: block.x0) if len(named) >= 2 else []


def _bands_from_centers(centers: list[float], width: float) -> list[tuple[float, float]]:
    """把各列中心换算成以相邻中点为分界的 [start, end) 区间."""
    edges = [0.0] + [(a + b) / 2 for a, b in zip(centers, centers[1:], strict=False)] + [width]
    return list(zip(edges, edges[1:], strict=False))


def _cluster_number_columns(blocks: list[TextBlock], width: float) -> list[tuple[float, float]]:
    """兜底的几何办法：按 x 方向的间距把数字块归成一列列."""
    centers = sorted(block.center_x for block in blocks if _looks_numeric(block.text))
    if not centers:
        return []
    groups = [[centers[0]]]
    for center in centers[1:]:
        if center - groups[-1][-1] > width * 0.12:
            groups.append([center])
        else:
            groups[-1].append(center)
    return _bands_from_centers([sum(group) / len(group) for group in groups], width)


def _looks_numeric(text: str) -> bool:
    """这个块基本就是个数字（可能带正负号、千分位分隔符、百分号）."""
    stripped = text.strip().replace(",", "").replace("%", "").replace("+", "").replace("−", "-")
    if stripped.startswith("-"):
        stripped = stripped[1:]
    return bool(stripped) and all(char.isdigit() or char == "." for char in stripped)


def build_layout(page: OcrPage) -> PageLayout:
    """读出一页的表头，并据此推出各列的竖向区间."""
    header = find_header(page.blocks)
    heights = sorted(block.height for block in page.blocks) or [20.0]

    if header:
        spans = _bands_from_centers([block.center_x for block in header], page.width)
        columns = []
        for (x0, x1), caption in zip(spans, header, strict=False):
            upper, lower = parse_caption(caption.text)
            columns.append(ColumnBand(x0=x0, x1=x1, upper=upper, lower=lower, caption=caption.text))
        return PageLayout(
            columns=tuple(columns),
            header_y=min(block.center_y for block in header),
            median_height=heights[len(heights) // 2],
        )

    spans = _cluster_number_columns(page.blocks, page.width)
    if not spans:
        return PageLayout(columns=(), named=False, median_height=heights[len(heights) // 2])
    # 最左边的文字列是基金名称，数字分组依次排在它右边。
    columns = [ColumnBand(x0=0.0, x1=spans[0][0], upper="name")]
    columns.extend(ColumnBand(x0=x0, x1=x1) for x0, x1 in spans)
    return PageLayout(columns=tuple(columns), named=False, median_height=heights[len(heights) // 2])
