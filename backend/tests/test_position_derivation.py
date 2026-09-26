"""Snapshot fields a holdings import may leave empty are derived, not read as zero."""

from app.models.portfolio import PortfolioPosition
from app.services.portfolio_service import position_profit, position_shares


def _position(**values: object) -> PortfolioPosition:
    return PortfolioPosition(user_id=1, account_id=1, fund_code="011452", **values)  # pyright: ignore[reportCallIssue]


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
