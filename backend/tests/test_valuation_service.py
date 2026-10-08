"""估值服务的口径判定：全部用真实档案里的基准原文与库里出现过的基金名."""

from datetime import date

from app.integrations.valuation.benchmark import parse_benchmark
from app.models.fund import Fund
from app.schemas.fund import FundHoldingItem, FundHoldingsResponse
from app.schemas.market import IndexQuoteItem
from app.services.valuation_service import _benchmark_ready, _is_cross_timezone_calendar, estimate_one

DAY = date(2026, 9, 30)

CSI300_BENCHMARK = "沪深300指数收益率×95%＋银行活期存款利率（税后）×5%"
# 011452 原文：A 股主动基金带 20% 港股基准，主口径仍在 A 股。
QUALITY_BENCHMARK = "中证800指数收益率*60%+恒生指数收益率（使用估值汇率折算）*20%+上证国债指数收益率*20%"
NASDAQ_BENCHMARK = "经汇率调整的纳斯达克100指数收益率*95%+活期存款利率（税后）*5%"
# 023597 原文：跟踪中证港股通创新药。港股与 A 股同一个交易时段，不该按境外处理。
HK_PHARMA_BENCHMARK = "中证港股通创新药指数收益率*95%+银行活期存款利率(税后)*5%"
# 恒生科技指数是腾讯有实时价的那条（hkHSTECH），基准法当场就能出数。
HSTECH_BENCHMARK = "恒生科技指数收益率*95%＋银行活期存款利率（税后）×5%"


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

        assert not _is_cross_timezone_calendar(fund, parse_benchmark(QUALITY_BENCHMARK))

    def test_the_dominant_benchmark_index_decides_the_calendar(self) -> None:
        assert _is_cross_timezone_calendar(
            _fund("012752", "建信纳斯达克100指数(QDII)人民币C"), parse_benchmark(NASDAQ_BENCHMARK)
        )

    def test_a_qdii_name_is_enough_when_the_type_column_is_empty(self) -> None:
        """库里 539001 的 fund_type 是 NULL，只有名字说明它是 QDII.

        只看类型列会静默放过这类基金，然后给它算出一个跟境外收盘无关的盘中数。
        """
        fund = _fund("539001", "建信纳斯达克100指数(QDII)A人民币", None)

        assert _is_cross_timezone_calendar(fund, parse_benchmark(None))


class TestSameTimezoneCalendar:
    def test_a_hang_kong_dominant_fund_is_not_refused(self) -> None:
        """港股与 A 股同时段：大头在港股不构成否决.

        早先的版本把"恒生/港股"一起当境外词，023597 这种中证港股通创新药的联接基金
        被静默判成"境外口径"，界面永远是一个空。
        """
        fund = _fund("023597", "景顺长城中证港股通创新药ETF联接A", "指数型-股票")

        assert parse_benchmark(HK_PHARMA_BENCHMARK).dominant_market == "hk"
        assert not _is_cross_timezone_calendar(fund, parse_benchmark(HK_PHARMA_BENCHMARK))

    def test_a_hang_seng_tech_index_fund_gets_a_number(self) -> None:
        """基准里那条恒生科技一旦取到价，走的就是误差最小的基准法.

        解析器把「恒生科技指数收益率」吃成「恒生科技」，所以行情键也是这个去尾形式。
        """
        fund = _fund("013309", "恒生科技ETF联接A", "QDII")
        quotes = _quotes()
        quotes["恒生科技"] = _quote("恒生科技", -2.89)

        item = estimate_one("013309", fund=fund, plan=parse_benchmark(HSTECH_BENCHMARK), quotes=quotes, holdings=None)

        assert item.available and item.method == "index"
        assert item.change_pct is not None and item.change_pct < 0

    def test_a_cross_timezone_name_still_refuses_without_a_benchmark(self) -> None:
        """基准读不懂时，名字里有跨时区市场词仍然按不可估处理."""
        assert _is_cross_timezone_calendar(
            _fund("539001", "建信纳斯达克100指数(QDII)A人民币", None), parse_benchmark(None)
        )

    def test_a_hang_kong_name_does_not_refuse_without_a_benchmark(self) -> None:
        """同理，名字里只有港股词的，不该被一起误伤."""
        fund = _fund("013309", "华夏恒生科技ETF联接A", "QDII")

        assert not _is_cross_timezone_calendar(fund, parse_benchmark(None))

    def test_an_unrecognisable_qdii_stays_refused(self) -> None:
        """基准与名称都说不出市场时，QDII 按最保守的处理：不给数."""
        assert _is_cross_timezone_calendar(_fund("000001", "某境外主题精选混合", "QDII"), parse_benchmark(None))

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
        assert item.reason == "cross_timezone_calendar"
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
