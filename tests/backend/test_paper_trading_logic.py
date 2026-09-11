"""FORTRESS-T2: paper trading engine — pure logic tests (no DB, no network).

Every function in paper_trading.logic is deterministic: the same inputs
always produce the same trade lifecycle and metrics. No real broker
execution is exercised anywhere here or in the module itself.
"""
from decimal import Decimal

from paper_trading.logic import (
    PaperTradingConfig,
    compute_metrics,
    open_position_from_signal,
    simulate_exit,
)


def _signal(**overrides):
    base = {
        "id": 1,
        "symbol": "RELIANCE.NS",
        "suggested_entry": 2500.0,
        "stop_loss": 2450.0,
        "target": 2650.0,
        "generated_at": "2026-01-15 10:00:00",
    }
    base.update(overrides)
    return base


def _bar(date, low, high, close):
    return {"date": date, "low": low, "high": high, "close": close}


# ── open_position_from_signal ────────────────────────────────────────────


def test_open_position_uses_signal_entry_stop_and_target():
    config = PaperTradingConfig()
    result = open_position_from_signal(_signal(), config)

    assert result.accepted is True
    assert result.trade["signal_id"] == 1
    assert result.trade["symbol"] == "RELIANCE.NS"
    assert result.trade["entry_price"] == 2500.0
    assert result.trade["stop_price"] == 2450.0
    assert result.trade["target_price"] == 2650.0
    assert result.trade["status"] == "open"
    assert result.trade["quantity"] > 0
    assert result.trade["notional"] == round(result.trade["quantity"] * 2500.0, 2)


def test_open_position_normalizes_decimal_signal_values():
    signal = _signal(
        suggested_entry=Decimal("2500.00"),
        stop_loss=Decimal("2450.00"),
        target=Decimal("2650.00"),
    )

    result = open_position_from_signal(signal, PaperTradingConfig())

    assert result.accepted is True
    assert result.trade["entry_price"] == 2500.0
    assert result.trade["stop_price"] == 2450.0
    assert result.trade["target_price"] == 2650.0


def test_open_position_rejects_signal_with_no_entry_price():
    config = PaperTradingConfig()
    result = open_position_from_signal(_signal(suggested_entry=None, price_used=None), config)
    assert result.accepted is False
    assert "entry price" in result.reason
    assert result.trade is None


def test_open_position_falls_back_to_price_used_when_no_suggested_entry():
    config = PaperTradingConfig()
    result = open_position_from_signal(_signal(suggested_entry=None, price_used=1800.0), config)
    assert result.accepted is True
    assert result.trade["entry_price"] == 1800.0


def test_open_position_applies_fallback_stop_when_signal_has_none():
    config = PaperTradingConfig(fallback_stop_loss_pct=0.10)
    result = open_position_from_signal(_signal(stop_loss=None), config)
    assert result.accepted is True
    assert result.trade["stop_price"] == round(2500.0 * 0.90, 2)


def test_open_position_rejects_at_simultaneous_position_limit():
    config = PaperTradingConfig(max_simultaneous_positions=2)
    open_positions = [{"notional": 1000.0}, {"notional": 1000.0}]
    result = open_position_from_signal(_signal(), config, open_positions)
    assert result.accepted is False
    assert "simultaneous position limit" in result.reason


def test_open_position_rejects_at_max_exposure():
    config = PaperTradingConfig(max_total_exposure=5000.0)
    open_positions = [{"notional": 5000.0}]
    result = open_position_from_signal(_signal(), config, open_positions)
    assert result.accepted is False
    assert "exposure" in result.reason


def test_open_position_caps_notional_to_remaining_exposure_room():
    config = PaperTradingConfig(max_position_notional=100_000.0, max_total_exposure=10_000.0)
    open_positions = [{"notional": 7_000.0}]
    result = open_position_from_signal(_signal(), config, open_positions)
    assert result.accepted is True
    assert result.trade["notional"] <= 3_000.0 + 1e-6  # only 3,000 of exposure room left


def test_open_position_rejects_signal_missing_id():
    config = PaperTradingConfig()
    signal = _signal()
    del signal["id"]
    result = open_position_from_signal(signal, config)
    assert result.accepted is False
    assert "id" in result.reason


# ── simulate_exit ─────────────────────────────────────────────────────────


def test_simulate_exit_stop_hit_first():
    config = PaperTradingConfig()
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [_bar("2026-01-16", low=2440.0, high=2510.0, close=2460.0)]

    closed = simulate_exit(trade, price_path, config)
    assert closed["status"] == "closed"
    assert closed["exit_reason"] == "stop"
    assert closed["exit_price"] == 2450.0
    assert closed["exit_timestamp"] == "2026-01-16"
    assert closed["holding_period_days"] == 1
    assert closed["gross_pnl"] < 0  # a stop-out is a loss — never dressed up


def test_simulate_exit_target_hit():
    config = PaperTradingConfig()
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [
        _bar("2026-01-16", low=2480.0, high=2600.0, close=2590.0),
        _bar("2026-01-17", low=2600.0, high=2660.0, close=2655.0),
    ]

    closed = simulate_exit(trade, price_path, config)
    assert closed["exit_reason"] == "target"
    assert closed["exit_price"] == 2650.0
    assert closed["holding_period_days"] == 2
    assert closed["gross_pnl"] > 0


def test_simulate_exit_stop_takes_priority_over_target_in_same_bar():
    """A single bar whose range spans both stop and target is resolved
    conservatively (stop first) — never assumes the favorable fill."""
    config = PaperTradingConfig()
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [_bar("2026-01-16", low=2400.0, high=2700.0, close=2500.0)]

    closed = simulate_exit(trade, price_path, config)
    assert closed["exit_reason"] == "stop"


def test_simulate_exit_time_based_when_neither_touched():
    config = PaperTradingConfig(max_holding_period_days=3)
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [
        _bar("2026-01-16", low=2490.0, high=2520.0, close=2510.0),
        _bar("2026-01-17", low=2495.0, high=2530.0, close=2520.0),
        _bar("2026-01-18", low=2500.0, high=2540.0, close=2530.0),
        _bar("2026-01-19", low=2600.0, high=2660.0, close=2655.0),  # beyond the window — ignored
    ]

    closed = simulate_exit(trade, price_path, config)
    assert closed["exit_reason"] == "time"
    assert closed["exit_price"] == 2530.0  # close of the 3rd bar, not the 4th
    assert closed["holding_period_days"] == 3


def test_simulate_exit_returns_none_when_no_price_data():
    config = PaperTradingConfig()
    trade = open_position_from_signal(_signal(), config).trade
    assert simulate_exit(trade, [], config) is None


def test_simulate_exit_is_deterministic_for_identical_inputs():
    config = PaperTradingConfig()
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [_bar("2026-01-16", low=2440.0, high=2510.0, close=2460.0)]

    result_a = simulate_exit(trade, price_path, config)
    result_b = simulate_exit(dict(trade), list(price_path), config)
    assert result_a == result_b


def test_simulate_exit_models_costs_when_configured():
    config = PaperTradingConfig(cost_bps=10.0)  # 0.10% round-trip
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [_bar("2026-01-17", low=2600.0, high=2660.0, close=2655.0)]

    closed = simulate_exit(trade, price_path, config)
    assert closed["costs_modeled"] > 0
    assert closed["net_pnl"] == round(closed["gross_pnl"] - closed["costs_modeled"], 2)
    assert closed["net_pnl"] < closed["gross_pnl"]


def test_simulate_exit_without_cost_config_leaves_net_equal_gross():
    config = PaperTradingConfig(cost_bps=0.0)
    trade = open_position_from_signal(_signal(), config).trade
    price_path = [_bar("2026-01-17", low=2600.0, high=2660.0, close=2655.0)]

    closed = simulate_exit(trade, price_path, config)
    assert closed["costs_modeled"] == 0.0
    assert closed["net_pnl"] == closed["gross_pnl"]


# ── compute_metrics ───────────────────────────────────────────────────────


def test_compute_metrics_empty_trades_reports_zeros_not_fabricated_values():
    metrics = compute_metrics([])
    assert metrics["trade_count"] == 0
    assert metrics["total_net_pnl"] == 0.0
    assert metrics["win_rate_pct"] is None
    assert metrics["expectancy"] is None
    assert metrics["benchmark_excess_return_pct"] is None


def test_compute_metrics_does_not_assume_profitability_on_a_losing_set():
    losing_trades = [
        {"gross_pnl": -100.0, "net_pnl": -100.0, "notional": 1000.0},
        {"gross_pnl": -50.0, "net_pnl": -50.0, "notional": 1000.0},
    ]
    metrics = compute_metrics(losing_trades)
    assert metrics["total_net_pnl"] == -150.0
    assert metrics["win_rate_pct"] == 0.0
    assert metrics["portfolio_return_pct"] < 0


def test_compute_metrics_win_rate_avg_win_avg_loss_expectancy():
    trades = [
        {"gross_pnl": 200.0, "net_pnl": 200.0, "notional": 1000.0},
        {"gross_pnl": -100.0, "net_pnl": -100.0, "notional": 1000.0},
        {"gross_pnl": 300.0, "net_pnl": 300.0, "notional": 1000.0},
        {"gross_pnl": -50.0, "net_pnl": -50.0, "notional": 1000.0},
    ]
    metrics = compute_metrics(trades)
    assert metrics["trade_count"] == 4
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["avg_win"] == 250.0
    assert metrics["avg_loss"] == -75.0
    assert metrics["total_net_pnl"] == 350.0
    # expectancy = 0.5*250 + 0.5*(-75) = 87.5
    assert metrics["expectancy"] == 87.5


def test_compute_metrics_max_drawdown_over_sequential_equity_curve():
    # equity path: +100 -> 100 (peak), -300 -> -200 (drawdown 300), +50 -> -150
    trades = [
        {"gross_pnl": 100.0, "net_pnl": 100.0, "notional": 1000.0},
        {"gross_pnl": -300.0, "net_pnl": -300.0, "notional": 1000.0},
        {"gross_pnl": 50.0, "net_pnl": 50.0, "notional": 1000.0},
    ]
    metrics = compute_metrics(trades)
    assert metrics["max_drawdown"] == 300.0


def test_compute_metrics_benchmark_comparison():
    trades = [{"gross_pnl": 500.0, "net_pnl": 500.0, "notional": 10_000.0}]
    metrics = compute_metrics(trades, benchmark_return_pct=2.0)
    assert metrics["portfolio_return_pct"] == 5.0
    assert metrics["benchmark_excess_return_pct"] == 3.0


def test_compute_metrics_no_benchmark_given_reports_none_not_zero():
    trades = [{"gross_pnl": 500.0, "net_pnl": 500.0, "notional": 10_000.0}]
    metrics = compute_metrics(trades, benchmark_return_pct=None)
    assert metrics["benchmark_excess_return_pct"] is None
