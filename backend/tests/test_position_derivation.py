"""What a holdings row leaves open is derived here, never read as zero."""

from app.analytics.positions import position_figures
from app.services.portfolio_service import period_profit_loss


class TestStoredFiguresWin:
    def test_a_cost_the_import_carried_is_not_recomputed(self) -> None:
        figures = position_figures(market_value=23121.0, cost_amount=22232.0, profit_loss=889.0)
        assert figures.cost_amount == 22232.0
        assert figures.profit_loss == 889.0
        assert not figures.cost_derived

    def test_stored_cost_beats_the_nav_estimate(self) -> None:
        figures = position_figures(market_value=900.5, cost_amount=1019.19, unit_nav=3.0372, settled_nav=3.3905)
        assert figures.cost_amount == 1019.19

    def test_stored_profit_beats_the_nav_estimate(self) -> None:
        figures = position_figures(market_value=900.5, profit_loss=-50.0, unit_nav=3.0372, settled_nav=3.3905)
        assert figures.cost_amount == 950.5
        assert figures.profit_loss == -50.0


class TestCostFromTwoStoredFigures:
    def test_derives_from_amount_minus_profit(self) -> None:
        assert position_figures(market_value=23121.0, profit_loss=889.0).cost_amount == 22232.0

    def test_derives_from_amount_minus_cost(self) -> None:
        assert position_figures(market_value=23121.0, cost_amount=22232.0).profit_loss == 889.0

    def test_a_gain_over_the_recorded_cost_stays_positive(self) -> None:
        assert position_figures(market_value=800.0, cost_amount=1000.0).profit_loss == -200.0

    def test_amount_alone_invents_nothing(self) -> None:
        figures = position_figures(market_value=23121.0)
        assert figures.cost_amount is None
        assert figures.profit_loss is None
        assert figures.profit_loss_rate is None


class TestCostFromTheSettledNav:
    def test_amount_is_discounted_back_to_the_confirmation_day(self) -> None:
        figures = position_figures(market_value=900.5, unit_nav=3.0372, settled_nav=3.3905)
        assert figures.cost_amount is not None
        assert round(figures.cost_amount, 2) == 1005.25
        assert figures.cost_derived

    def test_profit_is_the_gap_between_the_two_prices(self) -> None:
        figures = position_figures(market_value=900.5, unit_nav=3.0372, settled_nav=3.3905)
        assert figures.profit_loss is not None
        assert round(figures.profit_loss, 2) == -104.75

    def test_a_purchase_after_the_last_published_nav_prices_at_cost(self) -> None:
        figures = position_figures(market_value=900.5, unit_nav=3.0372, settled_nav=3.0372)
        assert figures.cost_amount == 900.5
        assert figures.profit_loss == 0.0

    def test_nothing_without_the_day_it_settled_on(self) -> None:
        assert position_figures(market_value=900.5, unit_nav=3.0372).cost_amount is None

    def test_nothing_without_a_current_price(self) -> None:
        assert position_figures(market_value=900.5, settled_nav=3.3905).cost_amount is None

    def test_a_zero_nav_is_not_divided_by(self) -> None:
        assert position_figures(market_value=900.5, unit_nav=0.0, settled_nav=3.3905).cost_amount is None


class TestSharesAndCostPerShare:
    def test_stored_shares_win(self) -> None:
        assert position_figures(market_value=23121.0, shares=7000.0, unit_nav=3.4218).shares == 7000.0

    def test_amount_over_the_price_it_is_marked_at(self) -> None:
        shares = position_figures(market_value=23121.0, unit_nav=3.42).shares
        assert shares is not None
        assert round(shares, 2) == 6760.53

    def test_average_cost_nav_follows_cost_over_shares(self) -> None:
        figures = position_figures(market_value=23121.0, cost_amount=22232.0, shares=7000.0)
        assert figures.average_cost_nav is not None
        assert round(figures.average_cost_nav, 4) == 3.176

    def test_a_stored_average_cost_nav_is_left_alone(self) -> None:
        figures = position_figures(market_value=23121.0, cost_amount=22232.0, shares=7000.0, average_cost_nav=3.4)
        assert figures.average_cost_nav == 3.4

    def test_rate_is_profit_over_cost(self) -> None:
        figures = position_figures(market_value=23121.0, cost_amount=22232.0)
        assert figures.profit_loss_rate is not None
        assert round(figures.profit_loss_rate, 4) == 0.04


class TestPeriodProfitLoss:
    def test_amount_times_the_window_return(self) -> None:
        assert period_profit_loss(23121.0, 0.04) == 924.84

    def test_loss_window_returns_a_negative_amount(self) -> None:
        assert period_profit_loss(23121.0, -0.02) < 0

    def test_none_when_either_side_is_missing(self) -> None:
        assert period_profit_loss(None, 0.04) is None
        assert period_profit_loss(23121.0, None) is None
        assert period_profit_loss(None, None) is None
