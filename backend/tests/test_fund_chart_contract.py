"""Keep the shared frontend chart fixture compatible with the backend protocol."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.tools.fund import get_fund_holdings
from app.schemas.fund import FundHoldingItem, FundHoldingsResponse
from pydantic import ValidationError

from app.schemas.fund_analysis import FundChartReference, FundHoldingsCard, FundNavChart

holdings_tool_module = importlib.import_module("app.agent.tools.fund.get_fund_holdings")


def test_chart_reference_contains_only_the_public_fund_identifier() -> None:
    fixture = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fund-chart-reference.fixture.json"
    reference = FundChartReference.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert reference.fund_code == "000001"
    for extra in [{"points": []}, {"url": "https://example.com"}, {"costNav": 2}, {"user_id": 1}]:
        with pytest.raises(ValidationError):
            FundChartReference.model_validate({**reference.model_dump(), **extra})


def test_client_chart_fixture_matches_backend_schema() -> None:
    fixture = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fund-chart.fixture.json"
    chart = FundNavChart.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert chart.schema_version == 1
    assert chart.points[0].date == chart.observed_from
    assert chart.points[-1].date == chart.as_of
    assert chart.warnings


def test_client_holdings_fixture_matches_backend_schema() -> None:
    fixture = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fund-holdings.fixture.json"
    card = FundHoldingsCard.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert card.type == "holdings"
    assert card.report_date
    assert len(card.items) == 7


@pytest.mark.parametrize("with_valid_weight", [True, False])
async def test_holdings_tool_only_embeds_verified_public_weights(monkeypatch, with_valid_weight: bool) -> None:
    items = [
        FundHoldingItem(stock_code="600001", stock_name="测试A", weight=9.45 if with_valid_weight else None),
        FundHoldingItem(stock_code="600001", stock_name="重复", weight=None),
        FundHoldingItem(stock_code="600002", stock_name="缺失", weight=None),
        FundHoldingItem(stock_code="600003", stock_name="异常", weight=101),
    ]
    response = FundHoldingsResponse(fund_code="000001", quarter=None, items=items)
    monkeypatch.setattr(
        holdings_tool_module, "fund_service", SimpleNamespace(get_holdings=AsyncMock(return_value=response))
    )
    payload = json.loads((await get_fund_holdings.ainvoke({"fund_code": "000001"})).splitlines()[1])
    assert len(payload["top_holdings"]) == 4  # Research payload keeps missing values explicit.
    if not with_valid_weight:
        assert payload["holdings_code_block"] is None
        return
    card = FundHoldingsCard.model_validate_json(payload["holdings_code_block"].splitlines()[1])
    assert card.report_date == "披露期未知"
    assert card.items[0].weight == 9.45  # Percentage points, not a ratio or a return contribution.
    assert len(card.items) == 1 and card.warnings
