"""估值纯计算的口径：缺依据时给 None，不给看起来合理的数."""

from app.analytics.valuation import (
    HoldingWeight,
    benchmark_change,
    choose_method,
    penetration_change,
)


class TestBenchmarkChange:
    def test_weights_are_applied_to_each_named_index(self) -> None:
        """95% 仓位跟指数，指数涨 1% 时基金约 +0.95pp."""
        change = benchmark_change([("沪深300", 95.0)], {"沪深300": 1.0})

        assert change is not None
        assert round(change, 4) == 0.95

    def test_a_partial_benchmark_is_refused_rather_than_renormalised(self) -> None:
        """缺一个指数就不能用剩下的凑：那已经不是同一条基准了.

        中证800 + 恒生 + 国债 三段里只取到一段时，按 60% 权重算会把结果当成整条
        基准的涨跌，界面会显示一个系统性偏小的数。
        """
        parts = [("中证800", 60.0), ("恒生", 20.0), ("上证国债", 20.0)]

        assert benchmark_change(parts, {"中证800": 1.0, "上证国债": 0.1}) is None

    def test_the_cash_part_contributes_zero(self) -> None:
        """存款段没有行情可取，按 0 收益处理（见函数 docstring 的代价说明）."""
        change = benchmark_change([("沪深300", 95.0)], {"沪深300": -2.0})

        assert change is not None
        assert round(change, 4) == -1.9

    def test_an_empty_plan_gives_nothing(self) -> None:
        assert benchmark_change([], {"沪深300": 1.0}) is None


class TestPenetrationChange:
    def test_weights_are_normalised_by_the_quoted_part_of_the_portfolio(self) -> None:
        """前十大占 90%，其中取到价的占 55：分母用 55，不是 90 也不是 100."""
        holdings = [
            HoldingWeight("600519", 40.0),
            HoldingWeight("300750", 15.0),
            HoldingWeight("000858", 35.0),  # 取不到行情
        ]
        change = penetration_change(holdings, {"600519": 2.0, "300750": -1.0})

        assert change is not None
        assert round(change, 4) == round((40 * 2.0 + 15 * -1.0) / 55.0, 4)

    def test_a_thin_disclosure_is_not_extrapolated(self) -> None:
        """指数联接基金的前十大只占净值 1.8%，归一等于把噪声放大 55 倍."""
        holdings = [HoldingWeight("600519", 0.9), HoldingWeight("300750", 0.9)]

        assert penetration_change(holdings, {"600519": 2.0, "300750": -1.0}) is None

    def test_no_quoted_holding_gives_no_number(self) -> None:
        assert penetration_change([HoldingWeight("600519", 90.0)], {}) is None


class TestChooseMethod:
    def test_offshore_calendar_funds_are_never_estimated(self) -> None:
        """口径先于精度：QDII 的盘中数是在预测境外今晚的收盘."""
        assert choose_method(offshore_calendar=True, benchmark_ready=True, disclosed_coverage_pp=95.0) == "unavailable"

    def test_a_usable_benchmark_wins_over_penetration(self) -> None:
        """基准法实测 0.07pp 量级，穿透 0.4~0.5pp，能前者就不用后者."""
        assert choose_method(offshore_calendar=False, benchmark_ready=True, disclosed_coverage_pp=92.5) == "index"

    def test_penetration_is_the_fallback_for_active_holdings(self) -> None:
        assert (
            choose_method(offshore_calendar=False, benchmark_ready=False, disclosed_coverage_pp=92.5) == "penetration"
        )

    def test_thin_or_absent_data_stays_blank(self) -> None:
        assert (
            choose_method(offshore_calendar=False, benchmark_ready=False, disclosed_coverage_pp=1.8) == "unavailable"
        )

    def test_an_a_share_fund_with_an_offshore_benchmark_part_still_gets_penetration(self) -> None:
        """基准里带 10%~20% 港股不等于境外基金：那只是让基准法取不到价.

        实测 011452/017489/022287 三只 A 股主动基金都是这种基准，前十大覆盖
        84%~95%，把它们一并否决是错的。
        """
        assert (
            choose_method(offshore_calendar=False, benchmark_ready=False, disclosed_coverage_pp=94.6) == "penetration"
        )
