"""What a holdings row leaves open is derived here, never read as zero."""

from app.analytics.positions import LedgerRow, position_figures, price_buy, price_sell, project_ledger
from app.services.portfolio_service import period_profit_loss


class TestStoredFiguresWin:
    def test_a_cost_the_import_carried_is_not_recomputed(self) -> None:
        figures = position_figures(market_value=23121.0, cost_amount=22232.0, profit_loss=889.0)
        assert figures.cost_amount == 22232.0
        assert figures.profit_loss == 889.0
        assert not figures.cost_derived

    def test_a_cost_projected_from_the_ledger_is_not_recomputed(self) -> None:
        figures = position_figures(market_value=23121.0, cost_amount=22232.0)
        assert figures.cost_amount == 22232.0
        assert figures.profit_loss == 889.0

    def test_a_blank_row_stays_blank_rather_than_zero(self) -> None:
        assert position_figures().profit_loss is None


class TestCostFromTwoStoredFigures:
    def test_derives_from_amount_minus_profit(self) -> None:
        figures = position_figures(market_value=23121.0, profit_loss=889.0)
        assert figures.cost_amount == 22232.0
        assert figures.cost_derived

    def test_derives_from_amount_minus_cost(self) -> None:
        assert position_figures(market_value=23121.0, cost_amount=22232.0).profit_loss == 889.0

    def test_a_gain_over_the_recorded_cost_stays_positive(self) -> None:
        assert position_figures(market_value=800.0, cost_amount=1000.0).profit_loss == -200.0

    def test_amount_alone_invents_nothing(self) -> None:
        figures = position_figures(market_value=23121.0)
        assert figures.cost_amount is None
        assert figures.profit_loss is None
        assert figures.profit_loss_rate is None


class TestLedgerProjection:
    def test_buys_accumulate_shares_and_cost(self) -> None:
        totals = project_ledger(
            [
                LedgerRow(kind="BUY", shares=1000.0, amount=3000.0),
                LedgerRow(kind="BUY", shares=500.0, amount=1750.0),
            ]
        )
        assert totals.shares == 1500.0
        assert totals.cost_amount == 4750.0

    def test_a_partial_sell_carries_cost_out_at_the_average_held(self) -> None:
        # Half of a 3000/1000 holding leaves 1500 of cost, not the sale price:
        # the gain on the way out must stay in 持有收益, not vanish from the basis.
        totals = project_ledger(
            [
                LedgerRow(kind="BUY", shares=1000.0, amount=3000.0),
                LedgerRow(kind="SELL", shares=500.0, amount=2000.0),
            ]
        )
        assert totals.shares == 500.0
        assert totals.cost_amount == 1500.0

    def test_a_full_exit_leaves_no_negative_remainder(self) -> None:
        totals = project_ledger(
            [
                LedgerRow(kind="BUY", shares=1000.0, amount=3000.0),
                LedgerRow(kind="SELL", shares=1000.0, amount=3300.0),
            ]
        )
        assert totals.shares == 0.0
        assert totals.cost_amount == 0.0

    def test_a_sell_without_any_holding_changes_nothing(self) -> None:
        totals = project_ledger([LedgerRow(kind="SELL", shares=100.0, amount=400.0)])
        assert totals.shares == 0.0
        assert totals.cost_amount == 0.0

    def test_rebuying_after_a_full_exit_starts_the_basis_again(self) -> None:
        totals = project_ledger(
            [
                LedgerRow(kind="BUY", shares=1000.0, amount=3000.0),
                LedgerRow(kind="SELL", shares=1000.0, amount=3300.0),
                LedgerRow(kind="BUY", shares=200.0, amount=700.0),
            ]
        )
        assert totals.shares == 200.0
        assert totals.cost_amount == 700.0


class TestOrderPricing:
    def test_the_subscription_fee_buys_nothing_but_stays_in_cost(self) -> None:
        delta = price_buy(nav=3.0, amount=3030.0, fee=30.0)
        assert delta.shares == 1000.0
        assert delta.amount == 3030.0
        assert delta.fee == 30.0

    def test_a_redemption_credits_what_actually_arrived(self) -> None:
        delta = price_sell(nav=3.2, shares=1000.0, fee=16.0)
        assert delta.shares == 1000.0
        assert delta.amount == 3184.0

    def test_a_fee_free_buy_becomes_amount_over_nav(self) -> None:
        assert price_buy(nav=2.5, amount=1000.0).shares == 400.0


class TestCostFromTheCostPrice:
    def test_cost_is_the_stated_price_times_the_units(self) -> None:
        figures = position_figures(market_value=900.5, average_cost_nav=3.4537, shares=295.1)
        assert figures.cost_amount is not None
        assert round(figures.cost_amount, 2) == 1019.19
        assert figures.cost_derived
        assert round(figures.profit_loss, 2) == -118.69

    def test_a_cost_the_row_stores_still_wins(self) -> None:
        figures = position_figures(market_value=900.5, cost_amount=1019.19, average_cost_nav=4, shares=295.1)
        assert figures.cost_amount == 1019.19
        assert not figures.cost_derived

    def test_the_price_needs_units_to_multiply(self) -> None:
        assert position_figures(market_value=900.5, average_cost_nav=3.4537).cost_amount is None

    def test_units_come_from_the_amount_over_the_latest_nav(self) -> None:
        figures = position_figures(market_value=900.5, average_cost_nav=3.4537, unit_nav=3.0519)
        assert figures.shares is not None
        assert round(figures.shares, 2) == 295.06
        assert figures.cost_amount is not None
        assert round(figures.cost_amount, 2) == 1019.06

    def test_a_price_the_row_does_not_store_is_flagged_as_derived(self) -> None:
        assert position_figures(market_value=900.5, cost_amount=1019.19, shares=295.1).average_cost_nav_derived
        assert not position_figures(market_value=900.5, average_cost_nav=3.4537, shares=295.1).average_cost_nav_derived


class TestSharesAndCostPerShare:
    def test_stored_shares_win(self) -> None:
        assert position_figures(market_value=23121.0, shares=7000.0, unit_nav=3.4218).shares == 7000.0

    def test_amount_over_the_price_it_is_marked_at(self) -> None:
        shares = position_figures(market_value=23121.0, unit_nav=3.42).shares
        assert shares is not None
        assert round(shares, 2) == 6760.53

    def test_nothing_without_a_price_to_divide_by(self) -> None:
        assert position_figures(market_value=23121.0, unit_nav=None).shares is None
        assert position_figures(market_value=23121.0, unit_nav=0.0).shares is None
        assert position_figures(unit_nav=3.42).shares is None

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
