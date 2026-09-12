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
    assert summary([]) == {"max_profit": None, "max_loss": None, "breakevens": []}


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
