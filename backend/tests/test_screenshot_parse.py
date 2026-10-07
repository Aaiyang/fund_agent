"""截图识别导入做的是版面几何的活，所以这些测试锁定的也就是几何关系.

失败方式都很具体，而且每一种都会悄悄把一笔持仓的数认错：同一列里下面那个数落进了
上面那个字段、两行之间的资讯卡片被当成一只基金、「金选」标签粘进了基金名称、被裁掉
半截的行当成完整行导了进来。这里的文本块就是按真实 支付宝 页面的版面摆出来的。
"""

from app.integrations.holdings.base import RawExtractedPosition
from app.integrations.holdings.fields import parse_figure, to_positions
from app.integrations.holdings.layout import build_layout, find_header, parse_caption
from app.integrations.holdings.name_match import decide, rank_names, score_name, share_class_of
from app.integrations.holdings.ocr import OcrPage, TextBlock
from app.integrations.holdings.rows import read_rows

WIDTH = 1200.0
HEIGHT = 2670.0
LINE = 54.0

# 照真实页面的列中心来摆：名称在左、金额在中、收益在右
_NAME_X, _VALUE_X, _PROFIT_X = 72.0, 620.0, 976.0


def _block(text: str, x: float, y: float, width: float = 150.0) -> TextBlock:
    """屏幕上某个位置的一条识别结果（一个词或一个数）."""
    return TextBlock(text=text, x0=x, y0=y, x1=x + width, y1=y + LINE, score=0.99)


def _row(y: float, name: str, value: str, daily: str, profit: str, rate: str) -> list[TextBlock]:
    """完整的一行持仓：名称，加上每列里上下叠放的两个数."""
    return [
        _block(name, _NAME_X, y, 400.0),
        _block(value, _VALUE_X, y + 4),
        _block(daily, _VALUE_X, y + LINE + 4),
        _block(profit, _PROFIT_X, y + 2),
        _block(rate, _PROFIT_X, y + LINE + 6),
    ]


def _header() -> list[TextBlock]:
    """应用自己在页面上打出来的那张表头."""
    return [
        _block("名称", _NAME_X, 645, 95),
        _block("金额/昨日收益", _VALUE_X - 100, 650, 255),
        _block("持有收益/率", _PROFIT_X - 68, 647, 221),
    ]


def _page(*rows: list[TextBlock]) -> OcrPage:
    """带着表头的一页文本块."""
    blocks = [block for row in rows for block in row]
    return OcrPage(path="shot.jpg", width=WIDTH, height=HEIGHT, blocks=[*_header(), *blocks])


def _positions(*rows: list[TextBlock]) -> list[RawExtractedPosition]:
    page = _page(*rows)
    return to_positions(read_rows(page, build_layout(page)), build_layout(page))


class TestCaption:
    def test_a_paired_caption_names_both_fields_top_first(self) -> None:
        assert parse_caption("金额/昨日收益") == ("market_value", "daily_profit_loss")
        assert parse_caption("持有收益/率") == ("profit_loss", "profit_loss_rate")

    def test_a_caption_we_cannot_read_names_nothing(self) -> None:
        # 只把半列对上字段，就会把另外半列的数塞进这个字段里。
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
        # 数字仍然聚成两列，但没有任何一列敢认领自己是 市值。
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

    def test_a_row_cut_off_mid_figure_is_dropped_not_completed(self) -> None:
        # 半条持仓比没有持仓更糟：让用户重拍一张页面，也好过让他确认一行的
        # 昨日收益 根本就没在屏幕上出现过。
        assert not _positions(
            [
                _block("国泰中证动漫游戏", _NAME_X, 2368, 400),
                _block("555.93", _VALUE_X, 2368),
                _block("-34.69", _PROFIT_X, 2370),
                _block("/ULO", _PROFIT_X + 55, 2440, 90),
            ]
        )

    def test_a_rate_without_its_percent_is_left_out_rather_than_rescaled(self) -> None:
        # 4.68 可能是 4.68%，也可能是个裸小数；只有应用自己知道，所以这里什么都不认领。
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

    def test_a_dropped_seed_qualifier_still_matches(self) -> None:
        """支付宝 页面上印的是「嘉实信息产业股票C」，而名录里这只基金的名字带 发起式.

        拿页面上那个名字去名录里查，压根就没有这只基金；不肯把这个词折叠掉的话，
        用户手里真实持有的这一笔就永远匹配不出来。
        """
        directory = [("017489", "嘉实信息产业股票发起式C"), ("017488", "嘉实信息产业股票发起式A")]
        won = decide(rank_names("嘉实信息产业股票C", directory))
        assert won is not None and won.fund_code == "017489"

    def test_a_type_word_the_screenshot_adds_still_matches(self) -> None:
        """反过来的方向：支付宝 补上了 混合，而短名里恰好没有这个词."""
        directory = [("011452", "华泰柏瑞质量成长C"), ("008528", "华泰柏瑞质量成长A")]
        won = decide(rank_names("华泰柏瑞质量成长混合C", directory))
        assert won is not None and won.fund_code == "011452"

    def test_two_spellings_of_one_fund_are_not_rivals(self) -> None:
        """同一个代码在名录里既存了注册名，也存了法定名称.

        去掉套话之后两者折叠成同一个形态；同一只基金自己跟自己撞车不算竞争 —— 否则
        等它的主档行同步进来的那天，名称匹配就会悄无声息地再也不命中。
        """
        directory = [("001042", "华夏领先股票型证券投资基金"), ("001042", "华夏领先股票")]
        won = decide(rank_names("华夏领先股票", directory))
        assert won is not None and won.fund_code == "001042"

    def test_a_currency_sibling_still_has_to_be_chosen(self) -> None:
        """折叠套话不能把 人民币 和 美元现汇 之间的差别也一起猜没."""
        directory = [
            ("000055", "广发纳斯达克100ETF联接人民币(QDII)A"),
            ("270042", "广发纳斯达克100ETF联接美元(QDII)A"),
        ]
        assert decide(rank_names("广发纳斯达克100ETF联接A", directory)) is None

    def test_an_acronym_tail_is_not_a_share_class(self) -> None:
        """ETF/FOF/LOF 结尾那个 F 是产品名称的一部分，不是份额类别字母."""
        assert share_class_of("招商快线ETF") is None
        assert share_class_of("汇添富核心精选混合(LOF)") is None
        assert share_class_of("融通四季添利债券(LOF)C") == "c"

    def test_a_class_before_a_trailing_bracket_is_still_read(self) -> None:
        assert share_class_of("华夏大盘精选混合A(后端)") == "a"
