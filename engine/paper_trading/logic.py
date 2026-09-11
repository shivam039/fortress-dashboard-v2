"""
engine/paper_trading/logic.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FORTRESS-T2 — Paper Trading Engine.

Converts a Fortress signal (from the FORTRESS-T1 signal_ledger) into a
simulated position and measures its actual outcome against a price path —
no real broker execution anywhere in this module. Every function here is
pure (no DB, no network, no wall-clock `datetime.now()` in the simulation
path) so a trade lifecycle is fully deterministic and reproducible given
the same signal + price path + config.

Flow: signal -> open_position_from_signal() -> simulate_exit() -> a closed
trade dict -> compute_metrics() over a set of closed trades.

Persistence (utils/db.py's create_paper_trade/close_paper_trade/
fetch_paper_trades) is a thin, separate layer on top of this — this module
never writes to the DB itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

# Exit reasons, in the priority order simulate_exit() checks them within a
# single price bar. "stop" is checked before "target" when a bar's range
# could plausibly touch both (a large-range day) — a conservative
# assumption (never assume the best-case fill), not a data-driven one.
EXIT_REASON_STOP = "stop"
EXIT_REASON_TARGET = "target"
EXIT_REASON_TIME = "time"


@dataclass(frozen=True)
class PaperTradingConfig:
    """All position-sizing/risk limits are explicit config, not hardcoded —
    per FORTRESS-T2's "Make configurable" requirement."""

    max_position_notional: float = 100_000.0
    max_simultaneous_positions: int = 10
    max_total_exposure: float = 500_000.0
    max_holding_period_days: int = 30
    # Round-trip transaction cost, in basis points of notional. 0 (default)
    # means costs are not modeled — net_pnl then equals gross_pnl, and
    # callers/consumers should treat net_pnl as "gross, cost-unmodeled" in
    # that case rather than assuming a real net figure.
    cost_bps: float = 0.0
    # Fallback stop distance (fraction of entry price) used only when the
    # signal itself supplies no stop_loss — Fortress signals normally do
    # (check_institutional_fortress computes one from ATR), so this is a
    # safety net, not the primary stop-loss rule.
    fallback_stop_loss_pct: float = 0.05


@dataclass
class OpenPositionResult:
    accepted: bool
    reason: str
    trade: Optional[Dict[str, Any]] = None


def open_position_from_signal(
    signal: Dict[str, Any],
    config: PaperTradingConfig,
    open_positions: Sequence[Dict[str, Any]] = (),
) -> OpenPositionResult:
    """Turn one signal_ledger row into a simulated position, or reject it.

    `signal` is expected to carry (all from signal_ledger, see
    utils/db.py's record_signal_ledger_entries): `id`, `symbol`,
    `suggested_entry` and/or `price_used`, `stop_loss`, `target`,
    `generated_at`.

    Rejections are deterministic and explicit (never a silent no-op):
    no valid entry price, the simultaneous-position limit, or the
    exposure limit. `open_positions` is the caller's current open-trade
    list (each needs at least a `notional` key) — this function does not
    read any DB itself.
    """
    raw_entry_price = signal.get("suggested_entry") or signal.get("price_used")
    try:
        entry_price = float(raw_entry_price)
    except (TypeError, ValueError):
        entry_price = 0.0
    if entry_price <= 0:
        return OpenPositionResult(False, "no valid entry price on signal")

    signal_id = signal.get("id")
    if signal_id is None:
        return OpenPositionResult(False, "signal has no id to link the trade to")

    if len(open_positions) >= config.max_simultaneous_positions:
        return OpenPositionResult(False, "simultaneous position limit reached")

    current_exposure = sum(float(p.get("notional", 0.0)) for p in open_positions)
    room = config.max_total_exposure - current_exposure
    if room <= 0:
        return OpenPositionResult(False, "max exposure limit reached")

    notional = min(config.max_position_notional, room)
    quantity = notional / entry_price

    raw_stop_price = signal.get("stop_loss")
    try:
        stop_price = float(raw_stop_price)
    except (TypeError, ValueError):
        stop_price = 0.0
    if stop_price <= 0:
        stop_price = round(entry_price * (1 - config.fallback_stop_loss_pct), 2)
    raw_target_price = signal.get("target")
    try:
        target_price = float(raw_target_price) if raw_target_price else None
    except (TypeError, ValueError):
        target_price = None

    trade = {
        "signal_id": signal_id,
        "symbol": signal.get("symbol"),
        "entry_timestamp": signal.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entry_price": round(float(entry_price), 2),
        "quantity": round(quantity, 4),
        "notional": round(quantity * entry_price, 2),
        "stop_price": round(float(stop_price), 2),
        "target_price": round(float(target_price), 2) if target_price else None,
        "status": "open",
    }
    return OpenPositionResult(True, "opened", trade)


def simulate_exit(
    trade: Dict[str, Any],
    price_path: Sequence[Dict[str, Any]],
    config: PaperTradingConfig,
) -> Optional[Dict[str, Any]]:
    """Walk `price_path` (chronological bars *after* entry, each a dict with
    at least `date`, `high`, `low`, `close`) and determine how/when this
    position would have exited.

    Per-bar rule (first touch wins, checked in this fixed order so the
    result never depends on iteration/dict order): stop touched (bar's low
    <= stop) -> exit at the stop price; else target touched (bar's high >=
    target) -> exit at the target price. If neither triggers within
    `config.max_holding_period_days` bars, exit at the close of the last
    bar in that window ("time" exit).

    Returns None only when `price_path` is empty (nothing to simulate yet
    — e.g. exit data hasn't arrived), never an invented result.
    Deterministic: identical inputs always produce an identical trade.
    """
    if not price_path:
        return None

    stop = trade.get("stop_price")
    target = trade.get("target_price")
    window = price_path[: config.max_holding_period_days]

    for i, bar in enumerate(window, start=1):
        if stop is not None and bar["low"] <= stop:
            return _finalize_exit(trade, stop, EXIT_REASON_STOP, bar["date"], i, config)
        if target is not None and bar["high"] >= target:
            return _finalize_exit(trade, target, EXIT_REASON_TARGET, bar["date"], i, config)

    last_bar = window[-1]
    return _finalize_exit(trade, last_bar["close"], EXIT_REASON_TIME, last_bar["date"], len(window), config)


def _finalize_exit(
    trade: Dict[str, Any],
    exit_price: float,
    reason: str,
    exit_date: str,
    holding_period_days: int,
    config: PaperTradingConfig,
) -> Dict[str, Any]:
    quantity = trade["quantity"]
    entry_price = trade["entry_price"]
    gross_pnl = round((exit_price - entry_price) * quantity, 2)
    cost = round(trade["notional"] * (config.cost_bps / 10_000.0), 2) if config.cost_bps else 0.0
    net_pnl = round(gross_pnl - cost, 2)
    return {
        **trade,
        "status": "closed",
        "exit_timestamp": exit_date,
        "exit_price": round(float(exit_price), 2),
        "exit_reason": reason,
        "gross_pnl": gross_pnl,
        "costs_modeled": cost,
        "net_pnl": net_pnl,
        "holding_period_days": holding_period_days,
    }


def compute_metrics(
    closed_trades: Sequence[Dict[str, Any]],
    benchmark_return_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Aggregate metrics over a set of closed trades. Never assumes
    profitability: an empty trade list reports zeros/None, not a fabricated
    positive result, and every figure is computed directly from
    `closed_trades` — nothing here is estimated or looked up elsewhere.

    `benchmark_return_pct`, when given, is the benchmark's own return over
    the same period (e.g. Nifty 50) — comparison, not a claim of causality.
    """
    if not closed_trades:
        return {
            "trade_count": 0,
            "total_gross_pnl": 0.0,
            "total_net_pnl": 0.0,
            "win_rate_pct": None,
            "avg_win": None,
            "avg_loss": None,
            "expectancy": None,
            "max_drawdown": 0.0,
            "total_exposure": 0.0,
            "turnover": 0.0,
            "portfolio_return_pct": None,
            "benchmark_excess_return_pct": None,
        }

    net_pnls = [t["net_pnl"] for t in closed_trades]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    win_rate_pct = round(len(wins) / len(net_pnls) * 100, 2)
    avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    win_prob = len(wins) / len(net_pnls)
    expectancy = round(win_prob * avg_win + (1 - win_prob) * avg_loss, 2)

    # Max drawdown over the trade-sequence equity curve (not a daily mark-
    # to-market curve — trades are assumed sequential in the order given).
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in net_pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    total_notional = sum(t["notional"] for t in closed_trades)
    total_net_pnl = round(sum(net_pnls), 2)
    portfolio_return_pct = round((total_net_pnl / total_notional) * 100, 2) if total_notional else None
    benchmark_excess_return_pct = (
        round(portfolio_return_pct - benchmark_return_pct, 2)
        if portfolio_return_pct is not None and benchmark_return_pct is not None
        else None
    )

    return {
        "trade_count": len(closed_trades),
        "total_gross_pnl": round(sum(t["gross_pnl"] for t in closed_trades), 2),
        "total_net_pnl": total_net_pnl,
        "win_rate_pct": win_rate_pct,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "max_drawdown": round(max_drawdown, 2),
        "total_exposure": round(total_notional, 2),
        # Turnover = total notional traded (sum of entry notionals). No
        # re-entries/position scaling are modeled yet, so this equals
        # total_exposure for now — kept as its own field since the two
        # diverge once partial exits/re-entries are added.
        "turnover": round(total_notional, 2),
        "portfolio_return_pct": portfolio_return_pct,
        "benchmark_excess_return_pct": benchmark_excess_return_pct,
    }
