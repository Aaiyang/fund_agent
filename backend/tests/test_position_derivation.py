"""Snapshot fields a holdings import may leave empty are derived, not read as zero."""

from app.models.portfolio import PortfolioPosition
from app.services.portfolio_service import (
    daily_profit_rate,
    period_profit_loss,
    position_cost,
    position_profit,
    position_shares,
)


def _position(**values: object) -> PortfolioPosition:
    return PortfolioPosition(user_id=1, account_id=1, fund_code="011452", **values)  # pyright: ignore[reportCallIssue]


class TestPositionCost:
    def test_uses_the_stored_cost(self) -> None:
        assert position_cost(_position(cost_amount=22232.0, market_value=23121.0, profit_loss=889.0)) == 22232.0

    def test_derives_from_amount_minus_profit(self) -> None:
        assert position_cost(_position(market_value=23121.0, profit_loss=889.0)) == 22232.0

    def test_keeps_a_negative_cost_of_a_lost_position(self) -> None:
        assert position_cost(_position(market_value=800.0, profit_loss=-200.0)) == 1000.0

    def test_none_when_profit_is_the_missing_figure(self) -> None:
        assert position_cost(_position(market_value=23121.0)) is None
        assert position_cost(_position()) is None


class TestPositionProfit:
    def test_uses_the_stored_figure(self) -> None:
        assert position_profit(_position(profit_loss=889.0, market_value=23121.0, cost_amount=22232.0)) == 889.0

    def test_derives_from_amount_and_cost(self) -> None:
        assert position_profit(_position(market_value=23121.0, cost_amount=22232.0)) == 889.0

    def test_zero_without_either_figure(self) -> None:
        assert position_profit(_position(market_value=23121.0)) == 0.0


class TestPositionShares:
    def test_uses_the_stored_share_count(self) -> None:
        assert position_shares(_position(shares=7000.0, market_value=23121.0), 3.4218) == 7000.0

    def test_derives_from_amount_over_nav(self) -> None:
        shares = position_shares(_position(market_value=23121.0), 3.42)
        assert shares is not None
        assert round(shares, 2) == 6760.53

    def test_none_without_a_price_to_divide_by(self) -> None:
        assert position_shares(_position(market_value=23121.0), None) is None
        assert position_shares(_position(market_value=23121.0), 0.0) is None
        assert position_shares(_position(), 3.42) is None


class TestPeriodProfitLoss:
    def test_amount_times_the_window_return(self) -> None:
        assert period_profit_loss(23121.0, 0.04) == 924.84

    def test_loss_window_returns_a_negative_amount(self) -> None:
        assert period_profit_loss(23121.0, -0.02) < 0

    def test_none_when_either_side_is_missing(self) -> None:
        assert period_profit_loss(None, 0.04) is None
        assert period_profit_loss(23121.0, None) is None
        assert period_profit_loss(None, None) is None


class TestDailyProfitRate:
    def test_divides_by_yesterdays_value(self) -> None:
        # +889 on a book now worth 23121 moved 4.0% from 22232.
        assert round(daily_profit_rate(23121.0, 889.0), 4) == 0.04

    def test_loss_is_negative(self) -> None:
        assert daily_profit_rate(900.0, -100.0) == -0.1

    def test_none_without_a_base(self) -> None:
        assert daily_profit_rate(0.0, 0.0) is None
        assert daily_profit_rate(100.0, 100.0) is None
