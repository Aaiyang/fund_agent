"""Screenshot parsing is geometry, so geometry is what these tests pin down.

The failure modes are specific and each one silently misprices a holding: a
column's lower figure landing in the upper field, a news card between two rows
becoming a fund, a 金选 chip glued onto the name, a clipped row importing as if
complete. Blocks here are laid out like the real 支付宝 page they came from.
"""

from app.integrations.holdings.fields import parse_figure, to_positions
from app.integrations.holdings.layout import build_layout, find_header, parse_caption
from app.integrations.holdings.name_match import decide, rank_names, score_name, share_class_of
from app.integrations.holdings.ocr import OcrPage, TextBlock
from app.integrations.holdings.rows import read_rows

WIDTH = 1200.0
HEIGHT = 2670.0
LINE = 54.0

# Column centres as the real page has them: name left, money middle, profit right.
_NAME_X, _VALUE_X, _PROFIT_X = 72.0, 620.0, 976.0


def _block(text: str, x: float, y: float, width: float = 150.0) -> TextBlock:
    """One recognized word/number at a spot on the screen."""
    return TextBlock(text=text, x0=x, y0=y, x1=x + width, y1=y + LINE, score=0.99)


def _row(y: float, name: str, value: str, daily: str, profit: str, rate: str) -> list[TextBlock]:
    """A complete holdings line: name plus two stacked figures in each column."""
    return [
        _block(name, _NAME_X, y, 400.0),
        _block(value, _VALUE_X, y + 4),
        _block(daily, _VALUE_X, y + LINE + 4),
        _block(profit, _PROFIT_X, y + 2),
        _block(rate, _PROFIT_X, y + LINE + 6),
    ]


def _header() -> list[TextBlock]:
    """The table header the app itself prints."""
    return [
        _block("名称", _NAME_X, 645, 95),
        _block("金额/昨日收益", _VALUE_X - 100, 650, 255),
        _block("持有收益/率", _PROFIT_X - 68, 647, 221),
    ]


def _page(*rows: list[TextBlock]) -> OcrPage:
    """A page of blocks with the header in place."""
    blocks = [block for row in rows for block in row]
    return OcrPage(path="shot.jpg", width=WIDTH, height=HEIGHT, blocks=[*_header(), *blocks])


def _positions(*rows: list[TextBlock]) -> list[object]:
    page = _page(*rows)
    return to_positions(read_rows(page, build_layout(page)), build_layout(page))


class TestCaption:
    def test_a_paired_caption_names_both_fields_top_first(self) -> None:
        assert parse_caption("金额/昨日收益") == ("market_value", "daily_profit_loss")
        assert parse_caption("持有收益/率") == ("profit_loss", "profit_loss_rate")

    def test_a_caption_we_cannot_read_names_nothing(self) -> None:
        # Half a column mapped to a field would put the other half's figure in it.
        assert parse_caption("最新净值/日涨幅") == (None, None)

    def test_the_header_needs_two_readable_columns_to_count(self) -> None:
        page = OcrPage(path="x", width=WIDTH, height=HEIGHT, blocks=[_block("名称", _NAME_X, 645)])
        assert find_header(page.blocks) == []


class TestLayout:
    def test_columns_are_split_between_the_header_centres(self) -> None:
        layout = build_layout(_page())
        assert [column.upper for column in layout.columns] == ["name", "market_value", "profit_loss"]
        assert layout.named and layout.header_y is not None

    def test_a_page_without_a_header_falls_back_to_geometry(self) -> None:
        page = OcrPage(
            path="x",
            width=WIDTH,
            height=HEIGHT,
            blocks=[*_row(850, "德邦鑫星价值灵活配置混合C", "846.07", "-20.87", "-21.46", "-2.80%")],
        )
        layout = build_layout(page)
        assert not layout.named
        # The numbers still group into two columns, but nothing claims to know which is 市值.
        assert [column.upper for column in layout.columns if column.upper != "name"] == [None, None]


class TestRows:
    def test_a_row_is_a_name_plus_figures(self) -> None:
        rows = read_rows(
            _page(_row(850, "德邦鑫星价值灵活配置混合C", "846.07", "-20.87", "-21.46", "-2.80%")),
            build_layout(_page()),
        )
        assert [row.name for row in rows] == ["德邦鑫星价值灵活配置混合C"]

    def test_a_news_card_between_rows_is_not_a_holding(self) -> None:
        page = _page(
            _row(850, "天弘沪深300ETF联接C", "837.57", "-7.35", "37.47", "+4.68%"),
            [_block("市场解读 4000点关口震荡，A股还能继续涨吗?", 177, 1324, 880)],
            _row(1560, "天弘恒生科技ETF联接(QDII)C", "745.45", "1.25", "-6.57", "-0.87%"),
        )
        rows = read_rows(page, build_layout(page))
        assert [row.name for row in rows] == ["天弘沪深300ETF联接C", "天弘恒生科技ETF联接(QDII)C"]

    def test_a_chip_under_the_name_stays_out_of_the_name(self) -> None:
        row = _row(850, "广发纳斯达克100ETF联接…", "577.46", "+12.55", "+33.28", "+6.23%")
        page = _page(row, [_block("金选指数基金", _NAME_X, 950, 300)])
        rows = read_rows(page, build_layout(page))
        assert [row.name for row in rows] == ["广发纳斯达克100ETF联接"]
        assert rows[0].tags == ("金选指数基金",)
        assert rows[0].truncated

    def test_the_bottom_navigation_is_not_a_holding(self) -> None:
        page = _page(
            _row(850, "德邦鑫星价值灵活配置混合C", "846.07", "-20.87", "-21.46", "-2.80%"),
            [_block("基金市场", 78, 2553, 140), _block("自选", 715, 2556, 76), _block("持有", 1011, 2553, 83)],
        )
        rows = read_rows(page, build_layout(page))
        assert len(rows) == 1

    def test_two_name_lines_join_in_reading_order(self) -> None:
        page = _page(
            [
                _block("德邦鑫星价值灵活", _NAME_X, 853, 400),
                _block("配置混合C", _NAME_X, 915, 240),
                _block("846.07", _VALUE_X, 857),
                _block("-20.87", _VALUE_X, 927),
                _block("-21.46", _PROFIT_X, 856),
                _block("-2.80%", _PROFIT_X, 927),
            ]
        )
        rows = read_rows(page, build_layout(page))
        assert [row.name for row in rows] == ["德邦鑫星价值灵活配置混合C"]


class TestFields:
    def test_the_stacked_figure_stays_in_its_own_field(self) -> None:
        position = _positions(_row(850, "德邦鑫星价值灵活配置混合C", "846.07", "-20.87", "-21.46", "-2.80%"))[0]
        assert position.market_value == 846.07  # pyright: ignore[reportAttributeAccessIssue]
        assert position.daily_profit_loss == -20.87  # pyright: ignore[reportAttributeAccessIssue]
        assert position.profit_loss == -21.46  # pyright: ignore[reportAttributeAccessIssue]
        assert position.profit_loss_rate == -2.8  # pyright: ignore[reportAttributeAccessIssue]

    def test_a_positive_rate_keeps_its_plus_sign(self) -> None:
        position = _positions(_row(850, "天弘沪深300ETF联接C", "837.57", "-7.35", "+37.47", "+4.68%"))[0]
        assert position.profit_loss == 37.47  # pyright: ignore[reportAttributeAccessIssue]
        assert position.profit_loss_rate == 4.68  # pyright: ignore[reportAttributeAccessIssue]

    def test_a_row_cut_off_mid_figure_is_flagged_not_guessed(self) -> None:
        position = _positions(
            [
                _block("国泰中证动漫游戏", _NAME_X, 2368, 400),
                _block("555.93", _VALUE_X, 2368),
                _block("-34.69", _PROFIT_X, 2370),
                _block("/ULO", _PROFIT_X + 55, 2440, 90),
            ]
        )[0]
        assert position.market_value == 555.93  # pyright: ignore[reportAttributeAccessIssue]
        assert position.profit_loss_rate is None  # pyright: ignore[reportAttributeAccessIssue]
        assert position.partial  # pyright: ignore[reportAttributeAccessIssue]

    def test_a_rate_without_its_percent_is_left_out_rather_than_rescaled(self) -> None:
        # 4.68 could be 4.68% or a fraction; only the app knows, so nothing is claimed.
        position = _positions(_row(850, "天弘沪深300ETF联接C", "837.57", "-7.35", "37.47", "4.68"))[0]
        assert position.profit_loss_rate is None  # pyright: ignore[reportAttributeAccessIssue]


class TestParseFigure:
    def test_separators_and_currency_are_dropped(self) -> None:
        assert parse_figure("¥1,234.56") == (1234.56, False)
        assert parse_figure("846.07") == (846.07, False)

    def test_every_dash_shape_reads_as_negative(self) -> None:
        for glyph in ("-", "−", "–", "—"):
            assert parse_figure(f"{glyph}21.46") == (-21.46, False)

    def test_a_half_glyph_is_not_a_number(self) -> None:
        assert parse_figure("/ULO") == (None, False)
        assert parse_figure("十") == (None, False)
        assert parse_figure("--") == (None, False)


class TestNameMatch:
    def test_a_tag_the_screenshot_adds_does_not_break_the_match(self) -> None:
        directory = [("012349", "天弘恒生科技ETF联接C"), ("012348", "天弘恒生科技ETF联接A")]
        assert decide(rank_names("天弘恒生科技ETF联接(QDII)C", directory)) is not None

    def test_share_classes_never_collapse_into_one_guess(self) -> None:
        directory = [
            ("006479", "广发纳斯达克100ETF联接人民币(QDII)C"),
            ("270042", "广发纳斯达克100ETF联接人民币(QDII)A"),
        ]
        matches = rank_names("广发纳斯达克100ETF联接", directory)
        assert len(matches) == 2
        assert decide(matches) is None

    def test_a_different_share_class_is_not_a_match(self) -> None:
        assert score_name("天弘沪深300ETF联接C", "天弘沪深300ETF联接A") == 0.0

    def test_a_stem_still_offers_candidates_for_a_misread_tail(self) -> None:
        matches = rank_names("国泰中证动漫游戏CTC联培C", [("012729", "国泰中证动漫游戏ETF联接C")])
        assert matches and matches[0].fund_code == "012729"
        assert decide(matches) is None

    def test_the_class_letter_comes_from_the_end_of_the_name(self) -> None:
        assert share_class_of("德邦鑫星价值灵活配置混合C") == "c"
        assert share_class_of("华泰柏瑞质量成长混合") is None
