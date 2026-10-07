"""估值服务的口径判定：全部用真实档案里的基准原文与库里出现过的基金名."""

from datetime import date

from app.integrations.valuation.benchmark import parse_benchmark
from app.models.fund import Fund
from app.schemas.fund import FundHoldingItem, FundHoldingsResponse
from app.schemas.market import IndexQuoteItem
from app.services.valuation_service import _benchmark_ready, _is_offshore_calendar, estimate_one

DAY = date(2026, 9, 30)

CSI300_BENCHMARK = "沪深300指数收益率×95%＋银行活期存款利率（税后）×5%"
# 011452 原文：A 股主动基金带 20% 港股基准，主口径仍在 A 股。
QUALITY_BENCHMARK = "中证800指数收益率*60%+恒生指数收益率（使用估值汇率折算）*20%+上证国债指数收益率*20%"
NASDAQ_BENCHMARK = "经汇率调整的纳斯达克100指数收益率*95%+活期存款利率（税后）*5%"


def _fund(code: str, name: str, fund_type: str | None = None) -> Fund:
    return Fund(fund_code=code, fund_name=name, fund_type=fund_type)


def _quote(name: str, change: float) -> IndexQuoteItem:
    return IndexQuoteItem(index_code="sh000300", name=name, close=4000.0, change_pct=change, trade_date=DAY)


def _quotes() -> dict[str, IndexQuoteItem]:
    return {
        "沪深300": _quote("沪深300", 1.0),
        "上证指数": _quote("上证指数", 0.4),
        "国债指数": _quote("国债指数", 0.05),
    }


def _holdings(code: str, pairs: list[tuple[str, float, float]], quarter: str = "2026年2季度") -> FundHoldingsResponse:
    return FundHoldingsResponse(
        fund_code=code,
        quarter=quarter,
        items=[
            FundHoldingItem(stock_code=symbol, symbol=symbol, weight=weight, change_pct=change)
            for symbol, weight, change in pairs
        ],
    )


class TestOffshoreCalendar:
    def test_a_minor_hang_kong_benchmark_part_does_not_disqualify_a_fund(self) -> None:
        """011452 的基准里恒生占 20%，但它是 A 股主动基金，穿透正是给它用的.

        早先的版本把"基准出现境外词"当否决条件，这类基金被一并判成不可估。
        """
        fund = _fund("011452", "华泰柏瑞质量成长C", "混合型-偏股")

        assert not _is_offshore_calendar(fund, parse_benchmark(QUALITY_BENCHMARK))

    def test_the_dominant_benchmark_index_decides_the_calendar(self) -> None:
        assert _is_offshore_calendar(
            _fund("012752", "建信纳斯达克100指数(QDII)人民币C"), parse_benchmark(NASDAQ_BENCHMARK)
        )

    def test_a_qdii_name_is_enough_when_the_type_column_is_empty(self) -> None:
        """库里 539001 的 fund_type 是 NULL，只有名字说明它是 QDII.

        只看类型列会静默放过这类基金，然后给它算出一个跟境外收盘无关的盘中数。
        """
        fund = _fund("539001", "建信纳斯达克100指数(QDII)A人民币", None)

        assert _is_offshore_calendar(fund, parse_benchmark(None))


class TestBenchmarkReady:
    def test_every_index_of_the_benchmark_must_be_quotable(self) -> None:
        plan = parse_benchmark(QUALITY_BENCHMARK)

        assert not _benchmark_ready(plan, _quotes())

    def test_a_single_index_benchmark_is_ready_when_that_index_is_quoted(self) -> None:
        assert _benchmark_ready(parse_benchmark(CSI300_BENCHMARK), _quotes())


class TestEstimateOne:
    def test_an_index_fund_is_estimated_from_its_benchmark(self) -> None:
        item = estimate_one(
            "005918",
            fund=_fund("005918", "天弘沪深300ETF联接C", "股票型-标准指数"),
            plan=parse_benchmark(CSI300_BENCHMARK),
            quotes=_quotes(),
            holdings=None,
        )

        assert item.available and item.method == "index"
        # 95% 仓位 × 指数 +1.0% ≈ +0.95pp，剩下 5% 存款按 0 处理。
        assert item.change_pct is not None and round(item.change_pct, 4) == 0.95
        assert item.basis == "沪深300×95%"
        assert item.quote_date == DAY

    def test_an_active_fund_falls_back_to_disclosed_holdings(self) -> None:
        holdings = _holdings("011452", [("600519", 40.0, 2.0), ("300750", 15.0, -1.0), ("000858", 37.5, 0.5)])
        item = estimate_one(
            "011452",
            fund=_fund("011452", "华泰柏瑞质量成长C", "混合型-偏股"),
            plan=parse_benchmark(QUALITY_BENCHMARK),
            quotes=_quotes(),
            holdings=holdings,
        )

        assert item.available and item.method == "penetration"
        assert item.basis == "已取到行情的持仓 92.5%（2026年2季度）"

    def test_a_qdii_fund_gets_no_number_and_says_why(self) -> None:
        item = estimate_one(
            "012752",
            fund=_fund("012752", "建信纳斯达克100指数(QDII)人民币C", "QDII-股票"),
            plan=parse_benchmark(NASDAQ_BENCHMARK),
            quotes=_quotes(),
            holdings=_holdings("012752", [("AAPL", 20.0, 1.0), ("MSFT", 20.0, 1.0)]),
        )

        assert not item.available
        assert item.method == "unavailable"
        assert item.reason == "offshore_calendar"
        assert item.change_pct is None

    def test_a_thin_disclosure_is_not_extrapolated(self) -> None:
        """005918 是联接基金，前十大只占 1.8%：基准取不到价时也不硬算."""
        item = estimate_one(
            "005918",
            fund=_fund("005918", "天弘沪深300ETF联接C", "股票型-标准指数"),
            plan=parse_benchmark("沪深300指数收益率×95%"),
            quotes={},
            holdings=_holdings("005918", [("600036", 0.9, 1.0), ("601318", 0.9, -1.0)]),
        )

        assert not item.available
        assert item.reason == "no_quotable_basis"

    def test_an_unknown_code_says_so_instead_of_returning_zero(self) -> None:
        item = estimate_one("999999", fund=None, plan=parse_benchmark(None), quotes=_quotes(), holdings=None)

        assert not item.available
        assert item.reason == "fund_not_found"
