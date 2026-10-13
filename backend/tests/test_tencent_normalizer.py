"""腾讯行情归一化层的测试.

用例是一个下标一个下标拼出来的，而不是直接粘贴真实报文：这个数据源是按位置用
``~`` 分隔的数组，每个市场的下标偏移都不一样 —— 在测试里逐个点名下标，上游一挪位，
各市场那张下标表就会立刻暴露出来。
"""

from datetime import date
from typing import Any

from app.integrations.fund_data.models import CandleExternalBar
from app.integrations.fund_data.normalizer import (
    market_kind,
    normalize_company_rows,
    parse_tencent_candles,
    parse_tencent_day_query,
    parse_tencent_minutes,
    parse_tencent_quotes,
    tencent_symbol,
)


def _line(symbol: str, size: int, **values: str) -> str:
    fields = [""] * size
    for key, value in values.items():
        fields[int(key.lstrip("f"))] = value
    return f'v_{symbol}="{"~".join(fields)}"'


def _quote(symbol: str, size: int, **values: str):
    return parse_tencent_quotes(_line(symbol, size, **values))[0]


class TestSymbolMapping:
    def test_six_digit_codes_split_by_exchange(self) -> None:
        assert tencent_symbol("600519") == "sh600519"
        assert tencent_symbol("300570") == "sz300570"
        assert tencent_symbol("09926") == "hk09926"

    def test_short_hong_kong_code_is_padded(self) -> None:
        assert tencent_symbol("1810") == "hk01810"

    def test_us_tickers_keep_their_case(self) -> None:
        assert tencent_symbol("NVDA") == "usNVDA"
        assert tencent_symbol("usNVDA.OQ") == "usNVDA.OQ"

    def test_ragged_input_is_rejected_not_passed_through(self) -> None:
        for code in ("", "  ", "sh600", "1234567890", "600519; rm", "../../etc/passwd", "A" * 40):
            assert tencent_symbol(code) is None, code

    def test_index_shapes_beat_the_overlapping_stock_codes(self) -> None:
        assert market_kind("sh000001") == "index"
        assert market_kind("sz399001") == "index"
        assert market_kind("bj899050") == "index"
        assert market_kind("sz000001") == "stock"


class TestQuoteParsing:
    def test_a_share_reads_valuation_and_caps(self) -> None:
        quote = _quote(
            "sh600519",
            88,
            f1="贵州茅台",
            f2="600519",
            f3="1237.00",
            f4="1251.24",
            f5="1250.01",
            f6="31239",
            f30="20260924161444",
            f31="-14.24",
            f32="-1.14",
            f33="1256.13",
            f34="1231.05",
            f35="1237.00/31239/3867310920",
            f38="0.25",
            f39="18.99",
            f43="2.00",
            f44="15463.51",
            f45="15463.51",
            f46="6.15",
            f67="1539.98",
            f68="1151.01",
            f82="CNY",
        )
        assert quote.kind == "stock"
        assert quote.name == "贵州茅台"
        assert quote.price == 1237.00
        assert quote.change_pct == -1.14
        # A股的 成交额 装在字段 35 里，单位已经是 元。
        assert quote.amount == 3_867_310_920.0
        assert quote.volume_unit == "手"
        assert quote.pb == 6.15
        assert (quote.week52_high, quote.week52_low) == (1539.98, 1151.01)
        assert quote.quote_time == "2026-09-24 16:14:44"

    def test_hong_kong_has_no_price_to_book_and_no_turnover(self) -> None:
        quote = _quote(
            "hk09926",
            78,
            f1="康方生物",
            f2="09926",
            f3="93.55",
            f35="93.55",
            f37="253782946.000",
            f38="0",
            f39="-69.93",
            f46="AKRO-BIO",
            f48="156.000",
            f49="80.200",
            f75="HKD",
        )
        assert quote.currency == "HKD"
        assert quote.amount == 253_782_946.0
        assert quote.volume_unit == "股"
        # 在这套版面里字段 46 是英文简称，不是 市净率。
        assert quote.pb is None
        # 港股 的 换手率 给出的是一个真 0，意思是「未披露」。
        assert quote.turnover_rate is None
        assert (quote.week52_high, quote.week52_low) == (156.0, 80.2)

    def test_us_listing_exposes_the_suffix_the_bars_need(self) -> None:
        quote = _quote("usNVDA", 73, f1="英伟达", f2="NVDA.OQ", f3="225.07", f35="USD", f37="20218422759")
        assert quote.listing_code == "NVDA.OQ"
        assert quote.currency == "USD"
        assert quote.volume_unit == "股"

    def test_index_keeps_its_own_level_and_drops_equity_valuation(self) -> None:
        quote = _quote(
            "sh000001",
            88,
            f1="上证指数",
            f2="000001",
            f3="3888.37",
            f35="3888.37/438530412/783613001376",
            f39="16.97",
            f46="0.00",
            f82="CNY",
        )
        assert quote.kind == "index"
        assert quote.pe is None
        assert quote.pb is None
        assert quote.amount == 783_613_001_376.0

    def test_blank_and_short_lines_are_skipped(self) -> None:
        assert parse_tencent_quotes('v_bad="";\nv_short="1~名称";') == []


class TestCandleParsing:
    def test_rows_are_date_open_close_high_low_not_ohlc(self) -> None:
        payload: dict[str, Any] = {
            "data": {
                "sh600519": {"qfqday": [["2026-09-24", "1250.010", "1237.000", "1256.130", "1231.050", "31239.000"]]}
            }
        }
        assert parse_tencent_candles(payload, "sh600519") == [
            CandleExternalBar(
                trade_date=date(2026, 9, 24),
                open=1250.010,
                close=1237.000,
                high=1256.130,
                low=1231.050,
                volume=31239.0,
            )
        ]

    def test_weekly_key_is_found_when_daily_is_absent(self) -> None:
        payload: dict[str, Any] = {"data": {"sh600519": {"qfqweek": [["2026-09-24", "1", "2", "3", "0.5", "10"]]}}}
        assert [bar.close for bar in parse_tencent_candles(payload, "sh600519")] == [2.0]

    def test_monthly_bars_are_read_from_either_key(self) -> None:
        # A股 返回的是带复权的那个 key；指数、港股 和 美股 明明请求的是 前复权，
        # 回来的却是不带复权的 key。
        row = ["2026-09-24", "3979.880", "3888.370", "3995.180", "3842.720", "8924426945.000"]
        for key, symbol in (("qfqmonth", "sh600519"), ("month", "sh000001"), ("month", "hk01810")):
            payload: dict[str, Any] = {"data": {symbol: {key: [row]}}}
            assert parse_tencent_candles(payload, symbol)[0].close == 3888.370, key

    def test_trailing_corporate_action_row_still_parses(self) -> None:
        row = [
            "2026-09-25",
            "26.180",
            "25.900",
            "26.200",
            "25.360",
            "78353485.000",
            {"cqr": "2026-09-25", "HGcontent": "回购"},
        ]
        payload: dict[str, Any] = {"data": {"hk01810": {"day": [row]}}}
        assert parse_tencent_candles(payload, "hk01810")[0].close == 25.900

    def test_empty_data_array_yields_no_bars(self) -> None:
        assert parse_tencent_candles({"data": []}, "sh600519") == []
        assert parse_tencent_candles({"data": {"sh600519": {}}}, "sh600519") == []


class TestMinuteParsing:
    def test_running_totals_become_per_minute_volumes(self) -> None:
        payload = _minute_payload("sh600519", ["0930 1250.01 183 22875182.71", "0931 1249.99 1393 174122899.37"])
        series = parse_tencent_minutes(payload, "sh600519")
        assert series.trade_date == date(2026, 9, 24)
        assert series.prev_close == 1251.24
        assert [point.time for point in series.points] == ["09:30", "09:31"]
        assert series.points[1].volume == 1210.0
        # 先把 手 换算成 股，再拿累计成交额除以累计成交量。
        assert series.points[0].average_price == 1250.01

    def test_index_sessions_have_no_average_price(self) -> None:
        payload = _minute_payload("sh000001", ["0930 3925.32 4098553 5934196660.3"])
        assert parse_tencent_minutes(payload, "sh000001").points[0].average_price is None

    def test_malformed_rows_are_dropped(self) -> None:
        payload = _minute_payload("sh600519", ["0930 1250.01", "0931 -- 1393 174122899.37"])
        assert parse_tencent_minutes(payload, "sh600519").points == []


class TestFiveDayParsing:
    def test_days_are_stitched_oldest_first_with_dates(self) -> None:
        payload = _day_payload(
            "sh600519",
            [
                ("20260924", ["0930 1250.01 183 22875182.71"]),
                ("20260923", ["0930 1255.03 63 7906688.70"]),
            ],
        )
        series = parse_tencent_day_query(payload, "sh600519")
        assert [point.trade_date for point in series.points] == [date(2026, 9, 23), date(2026, 9, 24)]
        assert series.trade_date == date(2026, 9, 24)
        # 五日窗口这种回复里不带昨收基准。
        assert series.prev_close is None

    def test_running_totals_reset_every_session(self) -> None:
        payload = _day_payload(
            "sh600519",
            [
                ("20260924", ["0930 1250.01 183 22875182.71", "0931 1249.99 1393 174122899.37"]),
                ("20260923", ["0930 1255.03 63 7906688.70", "0931 1254.00 900 60000000.00"]),
            ],
        )
        volumes = [point.volume for point in parse_tencent_day_query(payload, "sh600519").points]
        assert volumes == [63.0, 837.0, 183.0, 1210.0]

    def test_markets_without_history_come_back_empty(self) -> None:
        assert parse_tencent_day_query({"data": []}, "usNVDA").points == []
        assert parse_tencent_day_query({"data": {"usNVDA": {"data": []}}}, "usNVDA").points == []


class TestCompanyProfile:
    def test_board_and_concepts_are_flattened(self) -> None:
        payload = {
            "result": {
                "data": [
                    {
                        "ORG_NAME": "贵州茅台酒股份有限公司",
                        "BOARD_NAME_1LEVEL": "食品饮料",
                        "REGIONBK": "贵州省",
                        "LISTING_DATE": "2001-08-27 00:00:00",
                        "MAIN_BUSINESS": "茅台酒及系列酒的生产与销售",
                        "TOTAL_NUM": "34992",
                        "CHAIRMAN": "陈华",
                        "BLGAINIAN": "白酒,上证50_",
                    }
                ]
            }
        }
        profile = normalize_company_rows(payload, "sh600519")
        assert profile is not None
        assert profile.industry == "食品饮料"
        assert profile.list_date == date(2001, 8, 27)
        assert profile.employees == 34992.0
        assert profile.concepts == ["白酒", "上证50_"]

    def test_missing_record_returns_none(self) -> None:
        assert normalize_company_rows({"result": {"data": []}}, "sh600519") is None
        assert normalize_company_rows({}, "sh600519") is None


def _minute_payload(symbol: str, rows: list[str]) -> dict[str, Any]:
    quote = [""] * 46
    quote[1] = "测试"
    quote[4] = "1251.24"
    return {
        "data": {symbol: {"data": {"data": rows, "date": "20260924"}, "qt": {f"v_ff_{symbol}": [], symbol: quote}}}
    }


def _day_payload(symbol: str, sessions: list[tuple[str, list[str]]]) -> dict[str, Any]:
    """数据源返回的交易日是最新在前，这里也按同样的顺序拼."""
    days = [{"date": day, "data": rows} for day, rows in sessions]
    return {"data": {symbol: {"data": days}}}
