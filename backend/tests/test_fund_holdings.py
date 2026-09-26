"""Holdings parsing: mixed-market quote symbols and the quarter-over-quarter diff."""

from datetime import date

from app.integrations.fund_data.models import FundExternalHolding
from app.integrations.fund_data.normalizer import (
    normalize_industry_rows,
    parse_quarter,
    parse_sina_quotes,
    sina_symbol,
)
from app.services.fund_service import summarize_holdings

A_SHARE_LINE = (
    # Real layout is 34 fields with the date at 30 and the time at 31.
    'var hq_str_sz300308="中际旭创,900.00,922.40,895.86,905.00,880.00,895.00,895.86,123456,11000000000,'
    + ",".join(["0"] * 20)
    + ',2026-09-24,16:29:45,00,D";'
)
HK_LINE = (
    'var hq_str_hk01810="XIAOMI-W,小米集团－Ｗ,26.180,26.580,26.200,25.360,25.900,-0.680,-2.558,'
    '25.90000,25.92000,2015748248,78353485,0.000,0.000,59.000,21.300,2026-09-25,16:08";'
)
US_LINE = (
    'var hq_str_gb_nvda="英伟达,225.0700,0.22,2026-09-26 09:48:48,0.4900,224.5000,226.0000,223.1000,'
    '230.0000,200.0000,38193112,21525454,3832843815573,16.85";'
)


def _holding(code: str, quarter: str, weight: float | None) -> FundExternalHolding:
    return FundExternalHolding(fund_code="011452", stock_code=code, stock_name=code, weight=weight, quarter=quarter)


class TestSinaSymbol:
    def test_shanghai_and_shenzhen_by_leading_digit(self) -> None:
        assert sina_symbol("600487") == "sh600487"
        assert sina_symbol("300308") == "sz300308"
        assert sina_symbol("002384") == "sz002384"

    def test_hong_kong_is_five_digits(self) -> None:
        assert sina_symbol("01810") == "hk01810"

    def test_lettered_tickers_become_us_symbols(self) -> None:
        assert sina_symbol("NVDA") == "gb_nvda"
        assert sina_symbol("BRK.B") == "gb_brk.b"

    def test_unrecognised_shapes_return_none(self) -> None:
        assert sina_symbol("1234") is None
        assert sina_symbol("含中文") is None


class TestParseSinaQuotes:
    def test_a_share_change_comes_from_the_previous_close(self) -> None:
        quotes = parse_sina_quotes(A_SHARE_LINE)
        assert len(quotes) == 1
        quote = quotes[0]
        assert quote.symbol == "sz300308"
        assert quote.name == "中际旭创"
        assert quote.price == 895.86
        assert quote.change_pct is not None
        assert round(quote.change_pct, 2) == -2.88
        assert quote.quote_time == "2026-09-24 16:29:45"

    def test_hk_and_us_carry_their_own_change_field(self) -> None:
        quotes = {quote.symbol: quote for quote in parse_sina_quotes("\n".join([HK_LINE, US_LINE]))}
        assert quotes["hk01810"].name == "小米集团－Ｗ"
        assert quotes["hk01810"].change_pct == -2.558
        assert quotes["gb_nvda"].price == 225.07
        assert quotes["gb_nvda"].change_pct == 0.22

    def test_empty_lines_are_dropped(self) -> None:
        assert parse_sina_quotes('var hq_str_sz300308="";') == []


class TestParseQuarter:
    def test_reads_the_reporting_period(self) -> None:
        assert parse_quarter("2026年2季度股票投资明细") == (2026, 2)

    def test_none_for_other_shapes(self) -> None:
        assert parse_quarter("2026-02") is None
        assert parse_quarter(None) is None


class TestSummarizeHoldings:
    def test_latest_quarter_wins_and_delta_uses_the_previous_one(self) -> None:
        holdings = [
            _holding("300308", "2026年1季度股票投资明细", 10.0),
            _holding("300502", "2026年1季度股票投资明细", 8.0),
            _holding("300308", "2026年2季度股票投资明细", 9.99),
            _holding("300502", "2026年2季度股票投资明细", 5.57),
        ]
        quarter, previous, items = summarize_holdings(holdings)
        assert (quarter, previous) == ("2026年2季度", "2026年1季度")
        assert [item.stock_code for item in items] == ["300308", "300502"]
        assert items[0].weight_change == -0.01
        assert items[1].weight_change == -2.43

    def test_new_entry_is_flagged_instead_of_having_no_delta(self) -> None:
        holdings = [
            _holding("300308", "2026年1季度股票投资明细", 10.0),
            _holding("600487", "2026年2季度股票投资明细", 7.47),
        ]
        _, _, items = summarize_holdings(holdings)
        assert len(items) == 1
        assert items[0].weight_change is None
        assert items[0].is_new is True

    def test_carried_over_entry_reports_a_delta_and_is_not_new(self) -> None:
        holdings = [
            _holding("300308", "2026年1季度股票投资明细", 10.0),
            _holding("300308", "2026年2季度股票投资明细", 9.99),
        ]
        _, _, items = summarize_holdings(holdings)
        assert items[0].weight_change == -0.01
        assert items[0].is_new is False

    def test_a_single_disclosure_proves_nothing_new(self) -> None:
        holdings = [_holding("300308", "2026年2季度股票投资明细", 9.99)]
        _, previous, items = summarize_holdings(holdings)
        assert previous is None
        assert items[0].is_new is False
        assert items[0].weight_change is None

    def test_rows_without_a_quarter_are_ignored(self) -> None:
        quarter, previous, items = summarize_holdings([_holding("300308", None, 9.99)])
        assert (quarter, previous, items) == (None, None, [])

    def test_only_the_top_ten_are_returned(self) -> None:
        holdings = [_holding(f"3000{i:02d}", "2026年2季度股票投资明细", float(20 - i)) for i in range(12)]
        _, _, items = summarize_holdings(holdings)
        assert len(items) == 10
        assert items[0].weight == 20.0


class TestNormalizeIndustryRows:
    def test_keeps_only_the_latest_period_and_sorts_by_weight(self) -> None:
        rows = [
            {"行业类别": "医疗保健", "占净值比例": "42.65", "市值": "9.4e8", "截止时间": "2025-12-31"},
            {"行业类别": "制造业", "占净值比例": "49.8", "市值": "7.8e4", "截止时间": "2026-06-30"},
            {"行业类别": "医疗保健", "占净值比例": "32.7", "市值": "5.1e8", "截止时间": "2026-06-30"},
        ]
        industries = normalize_industry_rows(rows, "022287")
        assert [industry.industry for industry in industries] == ["制造业", "医疗保健"]
        assert industries[0].as_of == date(2026, 6, 30)

    def test_strips_the_shenwan_index_prefix_and_drops_zero_rows(self) -> None:
        rows = [
            {"行业类别": "50通信服务", "占净值比例": "5.91", "截止时间": "2026-06-30"},
            {"行业类别": "45信息技术", "占净值比例": "0.00", "截止时间": "2026-06-30"},
        ]
        industries = normalize_industry_rows(rows, "011452")
        assert [industry.industry for industry in industries] == ["通信服务"]

    def test_empty_payload_yields_nothing(self) -> None:
        assert normalize_industry_rows([], "011452") == []
        assert normalize_industry_rows([{"占净值比例": "1"}], "011452") == []
