from options_algo.payoff import StrategyLeg, payoff, summary
from main import get_options_payoff, OptionsPayoffRequest
from utils.db import compare_options_snapshots


def test_long_call_payoff_and_breakeven():
    legs = [StrategyLeg("CE", strike=100, premium=10)]
    assert payoff(legs, [90, 100, 110]) == [-10.0, -10.0, 0.0]
    result = summary(legs, price_ceiling=140)
    assert result["breakevens"] == [110.0]
    assert result["max_loss"] == -10.0


def test_short_straddle_is_bounded_to_requested_price_range():
    legs = [
        StrategyLeg("CE", 100, 5, side="SELL"),
        StrategyLeg("PE", 100, 5, side="SELL"),
    ]
    assert payoff(legs, [100]) == [10.0]
    result = summary(legs, price_ceiling=200)
    assert result["breakevens"] == [90.0, 110.0]
    assert result["max_profit"] == 10.0


def test_empty_strategy_does_not_fabricate_zero_risk_metrics():
    assert summary([]) == {"max_profit": None, "max_loss": None, "breakevens": [],
                           "grid_max_profit": None, "grid_max_loss": None}


def test_theoretical_tails_are_not_grid_extrema():
    assert summary([StrategyLeg("CE", 100, 10)], price_ceiling=140)["max_profit"] is None
    assert summary([StrategyLeg("CE", 100, 10, side="SELL")], price_ceiling=140)["max_loss"] is None
    assert summary([StrategyLeg("PE", 100, 10)], price_ceiling=140)["max_profit"] == 90.0
    assert summary([StrategyLeg("PE", 100, 10, side="SELL")], price_ceiling=140)["max_loss"] == -90.0


def test_vertical_spreads_have_bounded_theoretical_risk():
    bull_call = [StrategyLeg("CE", 100, 10), StrategyLeg("CE", 110, 3, side="SELL")]
    bear_call = [StrategyLeg("CE", 100, 10, side="SELL"), StrategyLeg("CE", 110, 3)]
    bull_put = [StrategyLeg("PE", 100, 10, side="SELL"), StrategyLeg("PE", 110, 3)]
    bear_put = [StrategyLeg("PE", 100, 10), StrategyLeg("PE", 110, 3, side="SELL")]
    for legs in (bull_call, bear_call, bull_put, bear_put):
        result = summary(legs, price_ceiling=220)
        assert result["max_profit"] is not None
        assert result["max_loss"] is not None


def test_payoff_api_is_read_only_and_returns_requested_grid():
    request = OptionsPayoffRequest(
        legs=[{"option_type": "CE", "strike": 100, "premium": 10}],
        prices=[90, 110],
    )
    result = get_options_payoff(request)
    assert result["prices"] == [90, 110]
    assert result["payoff"] == [-10.0, 0.0]


def test_snapshot_comparison_is_explicit_when_history_is_insufficient(monkeypatch):
    monkeypatch.setattr("utils.db.fetch_options_snapshots", lambda *args, **kwargs: [])
    assert compare_options_snapshots("RELIANCE.NS") == {
        "status": "INSUFFICIENT_HISTORY", "latest": None,
        "previous": None, "changes": {},
    }
