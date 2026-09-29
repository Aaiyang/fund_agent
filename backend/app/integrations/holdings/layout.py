"""Page structure: what each column means, and where the table starts.

A holdings screenshot is a table, and the table usually prints its own header —
「金额/昨日收益」sits over one pair of numbers,「持有收益/率」over another. The
header is therefore read first and the columns are named from it instead of
being hardcoded per app, which is what lets the same parser handle 支付宝 and
anything shaped like it.

When a screenshot carries no header the columns stay unnamed: deciding that a
given money column is 市值 rather than 持仓成本 is a guess, and a guessed 市值
is a wrong holding saved to the ledger. Those rows still reach the review page,
just flagged.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.integrations.holdings.ocr import OcrPage, TextBlock

# The money fields a screenshot column can carry. `name` is the fund-name column.
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

# Caption fragments → field. Checked in order, so longer/more specific
# fragments come first: 「昨日收益」 must not be read as 「收益」.
_CAPTION_FRAGMENTS: tuple[tuple[str, Slot], ...] = (
    ("昨日收益", "daily_profit_loss"),
    ("当日收益", "daily_profit_loss"),
    ("日收益", "daily_profit_loss"),
    ("持有收益", "profit_loss"),
    ("累计收益", "profit_loss"),
    ("收益率", "profit_loss_rate"),
    # Headers abbreviate freely: 「持有收益/率」 names its lower figure 率.
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

# A column header stacks two figures under one caption: 「金额/昨日收益」.
_UPPER_FOR: dict[Slot, Slot | None] = {
    "market_value": "daily_profit_loss",
    "profit_loss": "profit_loss_rate",
    "cost_amount": "average_cost_nav",
}


@dataclass(frozen=True)
class ColumnBand:
    """One vertical slice of the screenshot and the fields it carries."""

    x0: float
    x1: float
    upper: Slot | None = None
    lower: Slot | None = None
    caption: str | None = None

    def holds(self, block: TextBlock) -> bool:
        """Whether a block belongs to this column, by its horizontal centre."""
        return self.x0 <= block.center_x < self.x1


@dataclass(frozen=True)
class PageLayout:
    """The parsed skeleton of one screenshot."""

    columns: tuple[ColumnBand, ...]
    header_y: float | None = None
    named: bool = True
    median_height: float = 20.0
    dropped: tuple[str, ...] = field(default_factory=tuple)

    def column_for(self, block: TextBlock) -> ColumnBand | None:
        """The column a block falls into, if any."""
        return next((column for column in self.columns if column.holds(block)), None)

    def slot_for(self, block: TextBlock, line: int) -> Slot | None:
        """Which field a block is, given its position within the column."""
        column = self.column_for(block)
        if column is None:
            return None
        return column.upper if line <= 0 else column.lower


def parse_caption(text: str) -> tuple[Slot | None, Slot | None]:
    """Map a header caption to the fields of its column, top figure first.

    「金额/昨日收益」 → (market_value, daily_profit_loss);
    「持有收益/率」 → (profit_loss, profit_loss_rate).
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
    """Whether a block reads like a table header rather than a holding."""
    return block.text.strip() in {"名称", "基金名称", "产品名称"} or "/" in block.text


def find_header(blocks: list[TextBlock]) -> list[TextBlock]:
    """The header row: two or more caption-like blocks sharing one line.

    Returns [] when the screenshot has no header to read — some apps put the
    column names in a filter bar instead, and mistaking that for a header
    would rename every column below it.
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
    """Turn column centres into [start, end) spans split at the midpoints."""
    edges = [0.0] + [(a + b) / 2 for a, b in zip(centers, centers[1:], strict=False)] + [width]
    return list(zip(edges, edges[1:], strict=False))


def _cluster_number_columns(blocks: list[TextBlock], width: float) -> list[tuple[float, float]]:
    """Fallback geometry: group numeric blocks into columns by x gaps."""
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
    """Whether a block is essentially a figure (with sign, separators, %)."""
    stripped = text.strip().replace(",", "").replace("%", "").replace("+", "").replace("−", "-")
    if stripped.startswith("-"):
        stripped = stripped[1:]
    return bool(stripped) and all(char.isdigit() or char == "." for char in stripped)


def build_layout(page: OcrPage) -> PageLayout:
    """Read a page's header and derive its column bands."""
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
    # The leftmost text column is the fund name; the numeric groups follow it.
    columns = [ColumnBand(x0=0.0, x1=spans[0][0], upper="name")]
    columns.extend(ColumnBand(x0=x0, x1=x1) for x0, x1 in spans)
    return PageLayout(columns=tuple(columns), named=False, median_height=heights[len(heights) // 2])
