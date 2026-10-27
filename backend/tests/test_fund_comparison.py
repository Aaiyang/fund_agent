"""基金对比的统一窗口、质量边界、参数及工具输出回归."""

import asyncio
import importlib
import json
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agent.skills import read_skill
from app.agent.tools.fund import get_fund_comparison_data
from app.agent.tools.registry import FUND_TOOLS
from app.analytics.fund_comparison import aligned_nav_metrics
from app.analytics.returns import NavPoint
from app.models.fund import Fund
from app.schemas.fund import FundNavHistoryResponse, FundNavPoint
from app.schemas.fund_comparison import FundComparisonRequest, FundComparisonSeriesRequest
from app.schemas.research import ResearchRequest
from app.services.fund_comparison_service import FundComparisonService
from app.utils.task_routing import infer_research_request, request_after_fund_selection

service_module = importlib.import_module("app.services.fund_comparison_service")
TODAY = date(2026, 10, 13)
START = date(2025, 10, 13)


def points(start=START, end=TODAY, multiplier=1.0):
    """确定性工作日日点，不使用外部数据源."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return [
        FundNavPoint(nav_date=day, unit_nav=multiplier * (1 + i / 1000))
        for i, day in enumerate(day for day in days if day.weekday() < 5)
    ]


@pytest.fixture
def histories(monkeypatch):
    data = {
        "000001": FundNavHistoryResponse(fund_code="000001", points=points()),
        "000002": FundNavHistoryResponse(fund_code="000002", points=points(multiplier=2)),
    }

    async def read(code, **kwargs):
        return data[code]

    reader = AsyncMock(side_effect=read)
    monkeypatch.setattr(service_module, "business_today", lambda: TODAY)
    monkeypatch.setattr(service_module.fund_service, "get_nav_history", reader)

    async def read_names(codes):
        return {code: Fund(fund_code=code, fund_name=f"基金{code}") for code in codes}

    monkeypatch.setattr(service_module.fund_repository, "get_funds", AsyncMock(side_effect=read_names))
    return data, reader


@pytest.mark.parametrize("codes", [["000001"], ["000001", "000001"], ["1", "000002"], [1, "000002"], ["000001"] * 4])
def test_invalid_comparison_codes_are_rejected(codes):
    with pytest.raises(ValidationError):
        FundComparisonRequest(fund_codes=codes)


def test_same_code_dedup_preserves_distinct_share_codes_and_forbids_identity():
    assert FundComparisonRequest(fund_codes=["000001", "000001", "000002"]).fund_codes == ["000001", "000002"]
    with pytest.raises(ValidationError):
        FundComparisonRequest.model_validate({"fund_codes": ["000001", "000002"], "user_id": 42})
    for queries in (["000001"], ["000001", "000001"]):
        with pytest.raises(ValidationError):
            ResearchRequest(intent="fund_comparison", fund_queries=queries)
    with pytest.raises(ValidationError):
        ResearchRequest(intent="fund_comparison", fund_queries=["000001", "000002"], proposed_amount=200.0)


@pytest.mark.parametrize(
    "text,intent",
    [
        ("对比000001和000002", "fund_comparison"),
        ("深入比较000001与000002", "fund_comparison"),
        ("000001和000002哪个好", "fund_comparison"),
        ("分别分析000001和000002", "fund_research"),
        ("对比000001", None),
        ("不要比较000001和000002", None),
        ("不想研究000001", None),
        ("对比sh600519和000001", None),
        ("比较000001，我的订单号123456", None),
        ("结合我的持仓对比000001和000002", None),
    ],
)
def test_comparison_route_is_conservative(text, intent):
    request = infer_research_request(text)
    assert (request.intent if request else None) == intent


def test_after_selection_keeps_comparison_intent():
    request = request_after_fund_selection("比较成长和价值", ["000001", "000002"])
    assert request is not None and request.intent == "fund_comparison"


def test_hand_calculated_common_window_and_observed_drawdown():
    days = [date(2026, 10, i) for i in (9, 10, 11, 12)]
    series = {
        "000001": [NavPoint(day, nav) for day, nav in zip(days, (1, 2, 1, 1.5), strict=True)],
        "000002": [NavPoint(day, nav) for day, nav in zip(days[1:], (4, 5, 6), strict=True)],
    }
    common, rows = aligned_nav_metrics(series, {code: True for code in series})
    assert common == days[1:]
    assert rows["000001"].window_change_ratio == pytest.approx(-0.25)
    assert rows["000001"].observed_max_drawdown_ratio == pytest.approx(-0.5)
    assert rows["000002"].window_change_ratio == pytest.approx(0.5)
    assert rows["000002"].annualized_nav_volatility_ratio is None


def test_missing_common_daily_points_suppress_risk_without_interpolation():
    days = [date(2026, 10, i) for i in (9, 10, 11, 12)]
    series = {
        "000001": [NavPoint(day, nav) for day, nav in zip(days, (1, 4, 1, 2), strict=True)],
        "000002": [NavPoint(days[0], 1), NavPoint(days[-1], 2)],
    }
    common, rows = aligned_nav_metrics(series, {code: True for code in series})
    assert common == [days[0], days[-1]]
    assert rows["000001"].window_change_ratio == 1
    assert rows["000001"].observed_max_drawdown_ratio is None


async def test_complete_same_dates_keep_raw_metrics_and_do_not_return_series(histories):
    _, reader = histories
    result = await FundComparisonService().get_data(FundComparisonRequest(fund_codes=["000001", "000002"]))
    assert result.status == "completed" and result.common_from == START and result.common_to == TODAY
    assert result.rows[0].window_change_ratio == pytest.approx(result.rows[1].window_change_ratio)
    assert result.rows[0].annualized_nav_volatility_ratio is not None
    assert all(call.kwargs == {"start_date": START, "end_date": TODAY} for call in reader.await_args_list)
    text = await get_fund_comparison_data.ainvoke({"fund_codes": ["000001", "000002"]})
    payload = json.loads(text.splitlines()[1])
    assert payload["metric_basis"] == "unadjusted_unit_nav" and "points" not in payload
    assert "fund-chart" in text and "000002" in text
    assert get_fund_comparison_data in FUND_TOOLS
    assert read_skill("fund-comparison", "instructions").version == "1.1.0"


async def test_comparison_series_uses_fixed_window_and_starts_every_fund_at_zero(histories):
    data, reader = histories
    request = FundComparisonSeriesRequest(fund_codes=["000001", "000002"], from_date=START, to_date=TODAY)
    result = await FundComparisonService().get_series(request)

    assert result.common_from == START and result.common_to == TODAY
    assert result.aligned_count == len(data["000001"].points)
    assert [fund.fund_name for fund in result.funds] == ["基金000001", "基金000002"]
    assert all(len(fund.points) == result.aligned_count for fund in result.funds)
    assert all(fund.points[0].change_ratio == 0 for fund in result.funds)
    # 两只基金的净值比例在整个窗口内恒定，归一变化应完全相同。
    assert result.funds[0].points[-1].change_ratio == pytest.approx(result.funds[1].points[-1].change_ratio)
    assert result.funds[0].period_returns.return_1y == pytest.approx(result.funds[0].points[-1].change_ratio)
    assert result.funds[0].period_returns.return_1m is not None
    assert result.funds[0].period_returns.return_3m is not None
    assert result.funds[0].period_returns.return_6m is not None
    assert all(call.kwargs == {"start_date": START, "end_date": TODAY} for call in reader.await_args_list)


async def test_comparison_series_period_returns_leave_uncovered_months_empty(histories):
    request = FundComparisonSeriesRequest(
        fund_codes=["000001", "000002"],
        from_date=TODAY - timedelta(days=70),
        to_date=TODAY,
    )
    result = await FundComparisonService().get_series(request)
    periods = result.funds[0].period_returns

    assert periods.return_1m is not None
    assert periods.return_3m is None and periods.return_6m is None and periods.return_1y is None


def test_comparison_series_request_refuses_future_and_overlong_windows(monkeypatch):
    import app.schemas.fund_comparison as comparison_schema

    monkeypatch.setattr(comparison_schema, "business_today", lambda: TODAY)
    with pytest.raises(ValidationError):
        FundComparisonSeriesRequest(
            fund_codes=["000001", "000002"], from_date=START, to_date=TODAY + timedelta(days=1)
        )
    with pytest.raises(ValidationError):
        FundComparisonSeriesRequest(
            fund_codes=["000001", "000002"],
            from_date=TODAY - timedelta(days=400),
            to_date=TODAY,
        )
    with pytest.raises(ValidationError):
        FundComparisonSeriesRequest(fund_codes=["000001", "000002"], from_date=TODAY, to_date=TODAY)


async def test_short_new_fund_aligns_actual_window_and_marks_partial(histories):
    data, _ = histories
    data["000002"].points = points(start=TODAY - timedelta(days=70))
    result = await FundComparisonService().get_data(FundComparisonRequest(fund_codes=["000001", "000002"]))
    assert result.status == "partial" and result.common_from is not None and result.common_from > START
    assert all(row.annualized_nav_volatility_ratio is None for row in result.rows)
    assert any("未覆盖" in gap for gap in result.gaps)


async def test_three_funds_use_all_objects_and_one_reference_date(histories):
    data, reader = histories
    data["000003"] = FundNavHistoryResponse(
        fund_code="000003", points=points(start=TODAY - timedelta(days=180), multiplier=3)
    )
    result = await FundComparisonService().get_data(FundComparisonRequest(fund_codes=["000001", "000002", "000003"]))
    assert len(result.rows) == reader.await_count == 3
    assert result.common_from == data["000003"].points[0].nav_date
    assert len({row.aligned_count for row in result.rows}) == 1
    assert all(row.annualized_nav_volatility_ratio is not None for row in result.rows)
    data["000003"].points = data["000003"].points[-1:]
    unavailable = await FundComparisonService().get_data(
        FundComparisonRequest(fund_codes=["000001", "000002", "000003"])
    )
    assert unavailable.status == "unavailable" and all(row.window_change_ratio is None for row in unavailable.rows)


def test_sparse_weekly_dates_cannot_produce_annualized_daily_risk():
    series = {
        code: [NavPoint(START + timedelta(days=i * 7), 1 + i / 100) for i in range(50)]
        for code in ("000001", "000002")
    }
    _, rows = aligned_nav_metrics(series, {code: True for code in series})
    assert all(row.window_change_ratio is not None for row in rows.values())
    assert all(row.observed_max_drawdown_ratio is None for row in rows.values())
    assert all(row.annualized_nav_volatility_ratio is None for row in rows.values())


async def test_old_common_window_is_stale_even_if_each_fund_has_recent_nav(histories):
    data, _ = histories
    boundary = TODAY - timedelta(days=20)
    data["000001"].points = [point for point in data["000001"].points if point.nav_date <= boundary] + [
        FundNavPoint(nav_date=TODAY, unit_nav=2)
    ]
    data["000002"].points = [point for point in data["000002"].points if point.nav_date <= boundary] + [
        FundNavPoint(nav_date=TODAY - timedelta(days=1), unit_nav=3)
    ]
    result = await FundComparisonService().get_data(FundComparisonRequest(fund_codes=["000001", "000002"]))
    assert result.stale and result.status == "partial"
    assert not any(row.stale for row in result.rows)
    assert any("共同比较窗口截止" in gap for gap in result.gaps)


@pytest.mark.parametrize("kind", ["empty", "nonoverlap", "conflict", "truncated", "stale", "mismatch"])
async def test_bad_history_quality_is_not_silently_ranked(histories, kind):
    data, _ = histories
    history = data["000002"]
    if kind == "empty":
        history.points = []
    elif kind == "nonoverlap":
        data["000001"].points = points(end=START + timedelta(days=30))
        history.points = points(start=TODAY - timedelta(days=30))
    elif kind == "conflict":
        history.points.append(history.points[5].model_copy(update={"unit_nav": 999}))
    elif kind == "truncated":
        history.has_more = True
    elif kind == "stale":
        history.points = points(end=TODAY - timedelta(days=30))
    else:
        history.fund_code = "999999"
    result = await FundComparisonService().get_data(FundComparisonRequest(fund_codes=["000001", "000002"]))
    assert result.status != "completed" and result.gaps
    assert len(result.rows) == 2
    if kind in {"empty", "nonoverlap", "mismatch"}:
        assert result.status == "unavailable" and result.common_from is None
        assert all(row.window_change_ratio is None for row in result.rows)
    elif kind in {"conflict", "truncated"}:
        assert result.rows[1].annualized_nav_volatility_ratio is None


async def test_one_source_failure_preserves_all_targets(histories, monkeypatch):
    data, _ = histories

    async def read(code, **kwargs):
        if code == "000002":
            raise RuntimeError("private upstream error")
        return data[code]

    monkeypatch.setattr(service_module.fund_service, "get_nav_history", read)
    result = await FundComparisonService().get_data(FundComparisonRequest(fund_codes=["000001", "000002"]))
    assert result.status == "unavailable" and len(result.rows) == 2
    assert "private upstream" not in result.model_dump_json()


async def test_timeout_is_bounded_and_cancellation_propagates(histories, monkeypatch):
    monkeypatch.setattr(service_module, "_HISTORY_TIMEOUT", 0.01)

    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(service_module.fund_service, "get_nav_history", stalled)
    request = FundComparisonRequest(fund_codes=["000001", "000002"])
    async with asyncio.timeout(1):
        result = await FundComparisonService().get_data(request)
    assert result.status == "unavailable"
    task = asyncio.create_task(FundComparisonService().get_data(request))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_chart_reference_is_built_from_comparison_evidence_only():
    from app.agent.graph.research import fund_comparison_chart_ref
    from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask

    payload = {
        "status": "completed",
        "common_from": "2025-10-13",
        "common_to": "2026-10-13",
        "common_count": 240,
        "rows": [
            {
                "fund_code": "000001",
                "window_change_ratio": 0.12,
                "observed_max_drawdown_ratio": -0.08,
                "annualized_nav_volatility_ratio": 0.18,
                "aligned_count": 240,
                "stale": False,
            },
            {
                "fund_code": "000002",
                "window_change_ratio": -0.03,
                "observed_max_drawdown_ratio": -0.15,
                "annualized_nav_volatility_ratio": 0.22,
                "aligned_count": 240,
                "stale": True,
            },
        ],
    }
    evidence = ResearchEvidence(
        tool="get_fund_comparison_data",
        args={"fund_codes": ["000001", "000002"]},
        success=True,
        text="[TOOL_OK]\n{}",
        data=payload,
    )

    def state(intent: str) -> ResearchGraphState:
        return ResearchGraphState(
            turn_id="t",
            fund_codes=["000001", "000002"],
            evidence=[evidence],
            research_task=ResearchTask(
                turn_id="t",
                request=ResearchRequest(intent=intent, fund_queries=["000001", "000002"]),
                instruction="对比",
            ),
        )

    chart = fund_comparison_chart_ref(state("fund_comparison"))
    assert chart is not None
    assert chart.fund_codes == ["000001", "000002"] and chart.aligned_count == 240
    assert chart.funds[0].window_change_ratio == 0.12 and chart.funds[1].stale is True
    assert fund_comparison_chart_ref(state("fund_research")) is None

    unavailable = evidence.model_copy(update={"data": {**payload, "common_from": None, "common_to": None}})
    assert fund_comparison_chart_ref(state("fund_comparison").model_copy(update={"evidence": [unavailable]})) is None
