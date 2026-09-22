"""Third-party column names must never leak past the normalizer (spec 5.5)."""

from datetime import date, datetime

from app.integrations.fund_data.normalizer import (
    _pick,
    normalize_fund_record,
    normalize_nav_rows,
    normalize_profile_rows,
    to_date,
    to_float,
)


class TestToFloat:
    def test_parses_money_percent_and_placeholder_formats(self) -> None:
        assert to_float("1,234.56") == 1234.56
        assert to_float("2.20%") == 2.2
        assert to_float(" 3.1174 ") == 3.1174
        assert to_float(5) == 5.0

    def test_returns_none_for_missing_or_unparsable(self) -> None:
        for value in (None, "", "--", "-", "—", "nan", "abc", float("nan")):
            assert to_float(value) is None


class TestToDate:
    def test_accepts_the_formats_akshare_emits(self) -> None:
        assert to_date("2026-01-02") == date(2026, 1, 2)
        assert to_date("2026/01/02") == date(2026, 1, 2)
        assert to_date("20260102") == date(2026, 1, 2)
        assert to_date("2026-01-02 00:00:00") == date(2026, 1, 2)
        assert to_date(datetime(2026, 1, 2, 15, 4)) == date(2026, 1, 2)
        assert to_date(date(2026, 1, 2)) == date(2026, 1, 2)

    def test_returns_none_for_garbage(self) -> None:
        assert to_date("昨天") is None
        assert to_date(None) is None

    def test_survives_pandas_nat_and_nan_sentinels(self) -> None:
        """A single NaT cell must not take down a whole search (rank rows have them)."""

        class NaTType:  # pandas' NaT raises on any date use
            def date(self) -> date:
                raise TypeError("'float' object cannot be interpreted as an integer")

        assert to_date(NaTType()) is None
        assert to_date(float("nan")) is None
        assert to_date("NaT") is None


class TestMissingSentinels:
    def test_pick_skips_nan_nat_and_placeholder_strings(self) -> None:
        row = {"单位净值": float("nan"), "日期": "NaT", "基金简称": "  ", "基金代码": "011452"}
        assert _pick(row, "单位净值") is None
        assert _pick(row, "日期") is None
        assert _pick(row, "基金简称") is None
        assert _pick(row, "基金代码") == "011452"

    def test_real_zeroes_are_not_treated_as_missing(self) -> None:
        row = {"日增长率": 0.0, "单位净值": 0}
        assert to_float(_pick(row, "日增长率")) == 0.0
        assert to_float(_pick(row, "单位净值")) == 0.0


class TestNormalizeFundRecord:
    def test_maps_chinese_columns_and_pads_the_code(self) -> None:
        record = normalize_fund_record(
            {
                "基金代码": "11452",
                "基金简称": "华泰柏瑞质量成长混合C",
                "单位净值": "3.1174",
                "日期": "2026-09-18",
                "日增长率": "2.20%",
            }
        )
        assert record is not None
        assert (record.fund_code, record.fund_name) == ("011452", "华泰柏瑞质量成长混合C")
        assert (record.latest_nav, record.nav_date, record.daily_return) == (3.1174, date(2026, 9, 18), 2.2)

    def test_skips_rows_without_a_code(self) -> None:
        assert normalize_fund_record({"基金简称": "无代码"}) is None

    def test_tolerates_missing_optional_fields(self) -> None:
        record = normalize_fund_record({"基金代码": "011452", "基金简称": "示例基金"})
        assert record is not None
        assert (record.latest_nav, record.nav_date, record.fund_type) == (None, None, None)


class TestNormalizeProfile:
    def test_reads_item_value_rows_and_keeps_the_date_part(self) -> None:
        profile = normalize_profile_rows(
            [
                {"item": "基金简称", "value": "示例混合"},
                {"item": "基金类型", "value": "混合型-偏股"},
                {"item": "基金管理人", "value": "华泰柏瑞基金"},
                {"item": "基金经理", "value": "张三"},
                {"item": "成立日期/规模", "value": "2021-01-04/2.34亿"},
            ],
            "011452",
        )
        assert profile is not None
        assert profile.company == "华泰柏瑞基金"
        assert profile.inception_date == date(2021, 1, 4)

    def test_reads_the_renamed_inception_cell(self) -> None:
        # Current AKShare labels this 成立时间; matching only 成立日期 silently
        # leaves the fund detail page showing "--".
        profile = normalize_profile_rows(
            [
                {"item": "基金全称", "value": "示例混合型证券投资基金"},
                {"item": "成立时间", "value": "2021-02-19"},
            ],
            "011452",
        )
        assert profile is not None
        assert profile.fund_name == "示例混合型证券投资基金"
        assert profile.inception_date == date(2021, 2, 19)

    def test_keeps_slash_formatted_dates_whole(self) -> None:
        profile = normalize_profile_rows(
            [{"item": "基金简称", "value": "示例"}, {"item": "成立时间", "value": "2021/03/05"}],
            "011452",
        )
        assert profile is not None
        assert profile.inception_date == date(2021, 3, 5)

    def test_none_without_a_name(self) -> None:
        assert normalize_profile_rows([{"item": "基金类型", "value": "股票型"}], "011452") is None
        assert normalize_profile_rows([], "011452") is None


class TestNormalizeNavRows:
    def test_merges_unit_and_accumulated_by_date_descending(self) -> None:
        navs = normalize_nav_rows(
            unit_rows=[
                {"净值日期": "2026-09-17", "单位净值": "3.0", "日增长率": "1.0"},
                {"净值日期": "2026-09-18", "单位净值": "3.1174", "日增长率": "2.2"},
                {"净值日期": "bad", "单位净值": "9"},
            ],
            accumulated_rows=[{"净值日期": "2026-09-18", "累计净值": "4.2"}],
            fund_code="011452",
        )
        assert [nav.nav_date for nav in navs] == [date(2026, 9, 18), date(2026, 9, 17)]
        assert navs[0].accumulated_nav == 4.2
        assert navs[1].accumulated_nav is None
