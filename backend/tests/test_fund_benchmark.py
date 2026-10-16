"""业绩比较基准：原文与构成始终给，相对指标只在成分指数全部可查时给."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.analytics.returns import NavPoint
from app.analytics.risk_metrics import weighted_benchmark_series
from app.schemas.fund import FundNavPoint
from app.services import fund_benchmark_service as module
from app.utils.clock import business_today

HS300_BENCHMARK = "沪深300指数收益率×95%＋银行活期存款利率（税后）×5%"
# 相对指标的用例要一个没有现金段的基准：5% 现金按 0 收益合成后会拖低基准，
# beta 就不再是 1，断言会测到合成口径而不是指标本身。
HS300_FULL = "沪深300指数收益率*100%"
# parse_benchmark 的「(.*?)指数收益率」是非贪婪的，取出来的名字不含「指数」二字。
CSI800_BENCHMARK = "中证800指数收益率*60%+恒生指数收益率*20%+上证国债指数收益率*20%"
CSI800_PARTS = {"中证800", "恒生", "上证国债"}
COUNT = 200


def _fund_rows(step: float = 0.001) -> list[FundNavPoint]:
    """升序净值序列，日收益恒为 step，最后一日是业务今天."""
    end = business_today()
    return [
        FundNavPoint(nav_date=end - timedelta(days=COUNT - 1 - index), unit_nav=1.0 * (1 + step * index))
        for index in range(COUNT)
    ]


def _index_points(step: float = 0.001) -> list:
    """与净值序列同日期、同日收益的指数收盘，用来得到 beta=1 的可预期结果."""
    end = business_today()
    return [
        SimpleNamespace(trade_date=end - timedelta(days=COUNT - 1 - index), close=100.0 * (1 + step * index))
        for index in range(COUNT)
    ]


@pytest.fixture
def scenario(monkeypatch):
    state = SimpleNamespace(text=HS300_FULL, history=None, index_response="ok")
    monkeypatch.setattr(module.valuation_service, "benchmark_text", AsyncMock(side_effect=lambda code: state.text))
    monkeypatch.setattr(
        module.fund_service,
        "get_nav_history",
        AsyncMock(side_effect=lambda code, **kwargs: SimpleNamespace(fund_code=code, points=_fund_rows())),
    )

    async def history(index_code, range_key):
        if state.index_response != "ok":
            return None
        return SimpleNamespace(points=_index_points())

    monkeypatch.setattr(module.market_service, "get_history", AsyncMock(side_effect=history))
    return state


class TestWeightedBenchmarkSeries:
    def test_composes_normalized_weighted_series(self) -> None:
        first = [NavPoint(business_today() - timedelta(days=1), 100.0), NavPoint(business_today(), 110.0)]
        second = [NavPoint(business_today() - timedelta(days=1), 50.0), NavPoint(business_today(), 50.0)]
        series = weighted_benchmark_series([("A", 80.0), ("B", 20.0)], {"A": first, "B": second})
        assert len(series) == 2
        assert series[0].nav == pytest.approx(1.0)
        assert series[1].nav == pytest.approx(0.8 * 1.1 + 0.2 * 1.0)

    def test_cash_segment_holds_a_flat_floor(self) -> None:
        points = [NavPoint(business_today() - timedelta(days=1), 100.0), NavPoint(business_today(), 100.0)]
        series = weighted_benchmark_series([("A", 90.0)], {"A": points}, cash_weight=10.0)
        assert [point.nav for point in series] == pytest.approx([1.0, 1.0])

    def test_empty_when_a_component_is_missing_or_dates_do_not_overlap(self) -> None:
        points = [NavPoint(business_today() - timedelta(days=1), 100.0), NavPoint(business_today(), 101.0)]
        assert weighted_benchmark_series([("A", 50.0), ("B", 50.0)], {"A": points}) == []
        other = [
            NavPoint(business_today() + timedelta(days=5), 100.0),
            NavPoint(business_today() + timedelta(days=6), 101.0),
        ]
        assert weighted_benchmark_series([("A", 50.0), ("B", 50.0)], {"A": points, "B": other}) == []

    def test_empty_without_parts(self) -> None:
        assert weighted_benchmark_series([], {}) == []


class TestBenchmarkComposition:
    async def test_parses_text_into_weighted_index_parts(self, scenario) -> None:
        scenario.text = HS300_BENCHMARK
        data = await module.fund_benchmark_service.get_data("005918")
        assert data.parseable and data.benchmark_text == HS300_BENCHMARK
        assert [(item.index_name, item.weight_pp, item.index_code) for item in data.parts] == [
            ("沪深300", 95.0, "sh000300")
        ]
        assert data.cash_weight_pp == pytest.approx(5.0)

    async def test_missing_text_is_reported_not_guessed(self, scenario) -> None:
        scenario.text = None
        data = await module.fund_benchmark_service.get_data("005918")
        assert data.benchmark_text is None and not data.parseable and data.parts == []
        assert data.unavailable_reason is not None and data.beta is None

    async def test_index_outside_the_catalog_blocks_relative_metrics(self, scenario) -> None:
        scenario.text = CSI800_BENCHMARK
        data = await module.fund_benchmark_service.get_data("011452")
        # 原文与构成仍然给得出，缺的是相对指标——不能因为算不了就当基准不存在。
        assert data.parseable and {item.index_name for item in data.parts} == CSI800_PARTS
        assert data.beta is None and data.excess_return_ratio is None
        assert data.unavailable_reason is not None and "中证800" in data.unavailable_reason

    async def test_unavailable_index_history_is_disclosed(self, scenario) -> None:
        scenario.index_response = "none"
        data = await module.fund_benchmark_service.get_data("005918")
        assert data.unavailable_reason is not None and "沪深300" in data.unavailable_reason
        assert data.aligned_days == 0


class TestRelativeMetrics:
    async def test_identical_series_give_beta_one_and_zero_excess(self, scenario) -> None:
        data = await module.fund_benchmark_service.get_data("005918")
        assert data.unavailable_reason is None
        assert data.aligned_days == COUNT
        assert data.beta == pytest.approx(1.0)
        assert data.excess_return_ratio == pytest.approx(0.0, abs=1e-9)
        # 完美跟踪：超额收益恒为 0，跟踪误差没有可给的数，不是 0。
        assert data.tracking_error_ratio is None
        assert data.annual and all(row.excess_ratio == pytest.approx(0.0, abs=1e-9) for row in data.annual)

    async def test_annual_rows_flag_partial_years(self, scenario) -> None:
        data = await module.fund_benchmark_service.get_data("005918")
        assert data.annual[-1].full_year is False
        assert all(row.fund_ratio is not None and row.benchmark_ratio is not None for row in data.annual)

    async def test_relative_metric_caveats_are_published(self, scenario) -> None:
        data = await module.fund_benchmark_service.get_data("005918")
        joined = " ".join(data.warnings)
        assert "合成" in joined and "无风险利率 0" in joined and "未复权" in joined
