"""板块榜的解析与排名：新浪给的是定长逗号串，缺数必须是 None 而不是 0."""

import json

import pytest
from app.integrations.fund_data.sector_client import SectorDataUnavailable, parse_sina_board
from app.schemas.sector import SectorBoardItem
from app.services.sector_service import SectorService

_INDUSTRY_ROW = "new_blhy,玻璃行业,19,15.914210526316,-0.44157894736842,-2.6998326682971,598418073,13674354096,sh600629,10.012,18.020,1.640,华建集团"
_CONCEPT_ROW = "gn_hwqc,华为汽车,97,22.981979166667,-0.2809375,-1.2076624097723,2307718734,37821085106,sz002182,6.218,12.300,0.720,宝武镁业"
_MISSING_PCT_ROW = "new_x,未知板块,3,10.0,,,-,0,,0.0,0,0,"


def _payload(*rows: str) -> str:
    body = {row.split(",")[0]: row for row in rows}
    return "var S_Finance_bankuai_sinaindustry = " + json.dumps(body, ensure_ascii=False) + ";"


class TestParseSinaBoard:
    def test_maps_positional_columns(self) -> None:
        items = parse_sina_board(_payload(_INDUSTRY_ROW), "industry")
        assert len(items) == 1
        item = items[0]
        assert (item.code, item.name, item.sector_type) == ("new_blhy", "玻璃行业", "industry")
        assert item.stock_count == 19
        assert item.price == pytest.approx(15.914210526316)
        assert item.change == pytest.approx(-0.44157894736842)
        assert item.change_pct == pytest.approx(-2.6998326682971)
        assert item.amount == 13674354096
        assert item.leading_stock is not None
        assert (item.leading_stock.code, item.leading_stock.name) == ("sh600629", "华建集团")
        assert item.leading_stock.change_pct == pytest.approx(10.012)

    def test_concept_rows_keep_their_kind(self) -> None:
        items = parse_sina_board(_payload(_CONCEPT_ROW), "concept")
        assert items[0].sector_type == "concept"
        assert items[0].name == "华为汽车"

    def test_blank_and_placeholder_numbers_stay_unknown(self) -> None:
        item = parse_sina_board(_payload(_MISSING_PCT_ROW), "industry")[0]
        # 空串与 '-' 是"上游没说"，不能变成 0，否则榜单会把未知排成平盘。
        assert item.change is None
        assert item.change_pct is None
        assert item.volume is None
        assert item.leading_stock is None

    def test_rows_with_wrong_column_count_are_dropped(self) -> None:
        items = parse_sina_board(_payload(_INDUSTRY_ROW, "new_bad,只有三列,5"), "industry")
        assert [item.code for item in items] == ["new_blhy"]

    def test_unreadable_payload_raises(self) -> None:
        with pytest.raises(SectorDataUnavailable):
            parse_sina_board("var X = {不是 json};", "industry")
        with pytest.raises(SectorDataUnavailable):
            parse_sina_board("var X = [];", "industry")


def _item(code: str, change_pct: float | None, amount: float | None = None) -> SectorBoardItem:
    return SectorBoardItem(code=code, name=code, sector_type="industry", change_pct=change_pct, amount=amount)


class TestSectorBoardRanking:
    async def _items(self, kind: str) -> list[SectorBoardItem]:
        return [
            _item("平", 0.0, 5e8),
            _item("高", 3.5, 1e9),
            _item("低", -1.2, None),
            _item("未知", None, 9e9),
        ]

    async def test_desc_puts_gainers_first_and_unknowns_last(self, monkeypatch) -> None:
        monkeypatch.setattr(SectorService, "_board_items", self._items)
        result = await SectorService().board("industry", "desc", "change_pct", 4)
        assert [item.code for item in result.items] == ["高", "平", "低", "未知"]
        assert result.total_available == 3

    async def test_asc_reorders_but_unknowns_stay_at_the_tail(self, monkeypatch) -> None:
        monkeypatch.setattr(SectorService, "_board_items", self._items)
        result = await SectorService().board("industry", "asc", "change_pct", 4)
        assert [item.code for item in result.items] == ["低", "平", "高", "未知"]

    async def test_amount_sort_is_a_different_ranking_with_its_own_gaps(self, monkeypatch) -> None:
        """换排名指标时，缺的是另一个字段：成交额缺失的板块不能挤进榜里."""
        monkeypatch.setattr(SectorService, "_board_items", self._items)
        result = await SectorService().board("industry", "desc", "amount", 4)
        assert [item.code for item in result.items] == ["未知", "高", "平", "低"]
        assert result.total_available == 3
        assert any("成交额缺失" in warning for warning in result.warnings)

    async def test_limit_truncates_and_is_reported(self, monkeypatch) -> None:
        monkeypatch.setattr(SectorService, "_board_items", self._items)
        result = await SectorService().board("industry", "desc", "change_pct", 2)
        assert [item.code for item in result.items] == ["高", "平"]
        assert result.total_available == 3

    async def test_empty_upstream_returns_empty_list_with_warning(self, monkeypatch) -> None:
        async def none(self, kind: str) -> list[SectorBoardItem]:
            return []

        monkeypatch.setattr(SectorService, "_board_items", none)
        result = await SectorService().board("concept", "desc", "change_pct", 10)
        assert result.items == []
        assert any("取不到" in warning for warning in result.warnings)
