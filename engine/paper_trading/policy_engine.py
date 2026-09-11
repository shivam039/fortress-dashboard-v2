"""
engine/paper_trading/policy_engine.py — FORTRESS-E2: automated paper-trade
selection from real FORTRESS-T1 signals, orchestrating T2's existing engine
(engine/paper_trading/logic.py) without rewriting any of its trading math.

Pipeline this module implements:
  T1 signal (undecided) -> eligibility check -> next-session open price
  -> T2 open_position_from_signal() -> T2 create_paper_trade()
  ... next day ...
  open T2 trade -> real OHLCV since entry -> T2 simulate_exit()
  -> T2 close_paper_trade()

Every decision (OPENED / REJECTED_* / INVALID_SIGNAL / PENDING_ENTRY) is
persisted in paper_policy_decisions, keyed by signal_id, making reruns
idempotent and every non-open signal auditable. See
docs/research/AUTOMATED_PAPER_PORTFOLIO.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from utils.db import (
    close_paper_trade,
    create_paper_trade,
    fetch_paper_trades,
    fetch_policy_decisions,
    fetch_research_observations,
    fetch_signal_ledger,
    fetch_undecided_signals,
    upsert_policy_decision,
)

from paper_trading.logic import (
    PaperTradingConfig,
    compute_metrics,
    open_position_from_signal,
    simulate_exit,
)

POLICY_VERSION = "e2-policy-v1"


@dataclass(frozen=True)
class PaperPolicy:
    """One explicit, versioned configuration. Position sizing/exposure/
    holding-period/stop-target limits are T2's own PaperTradingConfig,
    reused as-is (not reinvented) — see PaperTradingConfig's own defaults
    for those. Fields below are the policy decisions specific to
    *automated* entry that T2's config does not already cover."""

    policy_version: str = POLICY_VERSION
    config: PaperTradingConfig = PaperTradingConfig(
        # Conservative documented default: T2's own dataclass default
        # (0.0) means "costs not modeled," appropriate for isolated
        # unit tests of exit logic. Automated prospective evidence
        # should reflect realistic round-trip friction instead of
        # silently reporting cost-free returns; 10bps round-trip is a
        # conservative, commonly-cited retail-equity estimate, not
        # fit to any observed outcome.
        cost_bps=10.0,
    )
    # Reuses Fortress's own existing quality gate (Quality_Gate_Pass, in
    # every signal's feature_snapshot) as "what counts as tradeable" —
    # deliberately not a new/second score threshold.
    require_quality_gate_pass: bool = True
    allow_duplicate_symbol: bool = False


def _feature_snapshot(signal: Dict[str, Any]) -> Dict[str, Any]:
    """fetch_undecided_signals() reads signal_ledger directly (a plain
    JOIN query) rather than through fetch_signal_ledger()'s own JSON-decode
    step, so feature_snapshot may still be a raw JSON string here on
    SQLite — normalize once, at the one call site that needs to read it."""
    snapshot = signal.get("feature_snapshot")
    if isinstance(snapshot, str):
        import json
        try:
            return json.loads(snapshot)
        except (TypeError, ValueError):
            return {}
    return snapshot if isinstance(snapshot, dict) else {}


def _healthy_scan_pairs() -> set:
    """(scan_id, symbol) pairs with a real E1 research observation. E1
    (FORTRESS-V4) already skips recording observations entirely for a
    circuit-broken scan, so the absence of a pair here is the existing,
    free signal that a scan was invalid — reused rather than adding a new
    column/flag to signal_ledger for the same fact."""
    return {(o.get("scan_id"), o.get("symbol")) for o in fetch_research_observations()}


def _is_signal_eligible(signal: Dict[str, Any], policy: PaperPolicy, healthy_pairs: set) -> tuple[bool, str]:
    entry = signal.get("suggested_entry") or signal.get("price_used")
    if not entry or entry <= 0:
        return False, "no valid entry price on signal"
    if (signal.get("scan_id"), signal.get("symbol")) not in healthy_pairs:
        return False, "no matching E1 research observation — source scan was invalid/circuit-broken"
    if policy.require_quality_gate_pass:
        if not _feature_snapshot(signal).get("Quality_Gate_Pass"):
            return False, "Quality_Gate_Pass is not true on this signal"
    return True, ""


def _next_session_open(symbol: str, signal_date: str, get_ohlcv_fn: Callable) -> Optional[float]:
    """The look-ahead-safe entry price: the Open of the first real trading
    session strictly after `signal_date`, using the fetched OHLCV series'
    own trading-day index (same technique as engine/research/
    prospective_store.py's maturation — no invented calendar). Returns
    None when that session hasn't happened yet (this run is too soon after
    the signal) — never an invented/early price."""
    try:
        hist = get_ohlcv_fn(symbol, "1y")
    except Exception:
        return None
    if hist is None or hist.empty or "Open" not in hist.columns:
        return None
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in hist.index]
    base_date = str(signal_date)[:10]
    later = [i for i, d in enumerate(dates) if d > base_date]
    if not later:
        return None
    idx = min(later)
    price = hist["Open"].iloc[idx]
    if price is None or (isinstance(price, float) and math.isnan(price)) or price <= 0:
        return None
    return float(price)


def process_new_signals(
    policy: Optional[PaperPolicy] = None, get_ohlcv_fn: Optional[Callable] = None, limit: int = 500,
    min_signal_id: Optional[int] = None,
) -> Dict[str, int]:
    """Evaluate every undecided signal deterministically (id ascending).
    Never silently discards one — each gets exactly one terminal or
    PENDING_ENTRY decision row."""
    policy = policy or PaperPolicy()
    if get_ohlcv_fn is None:
        from utils.market_data_provider import get_ohlcv as get_ohlcv_fn

    counts = {"considered": 0, "opened": 0, "rejected_max_positions": 0,
              "rejected_exposure": 0, "rejected_duplicate_symbol": 0,
              "rejected_policy": 0, "invalid_signal": 0, "pending_entry": 0}

    open_trades = fetch_paper_trades(status="open")
    open_symbols = {t["symbol"] for t in open_trades}
    healthy_pairs = _healthy_scan_pairs()

    # Also re-check any PENDING_ENTRY signals from a prior run whose next
    # session may have arrived by now.
    pending = fetch_policy_decisions(status="PENDING_ENTRY")
    pending_signals = [fetch_signal_ledger(signal_id=p["signal_id"], limit=1) for p in pending]
    signals = [s[0] for s in pending_signals if s] + fetch_undecided_signals(limit=limit, min_signal_id=min_signal_id)

    for signal in signals:
        counts["considered"] += 1
        sid = signal["id"]
        ok, reason = _is_signal_eligible(signal, policy, healthy_pairs)
        if not ok:
            upsert_policy_decision(sid, policy.policy_version, "INVALID_SIGNAL", reason)
            counts["invalid_signal"] += 1
            continue

        if not policy.allow_duplicate_symbol and signal["symbol"] in open_symbols:
            upsert_policy_decision(sid, policy.policy_version, "REJECTED_DUPLICATE_SYMBOL",
                                    "an open position already exists for this symbol")
            counts["rejected_duplicate_symbol"] += 1
            continue

        entry_price = _next_session_open(signal["symbol"], signal["generated_at"], get_ohlcv_fn)
        if entry_price is None:
            upsert_policy_decision(sid, policy.policy_version, "PENDING_ENTRY",
                                    "next valid session's open is not available yet")
            counts["pending_entry"] += 1
            continue

        entry_signal = {**signal, "suggested_entry": entry_price, "price_used": entry_price}
        result = open_position_from_signal(entry_signal, policy.config, open_trades)
        if not result.accepted:
            if "simultaneous position limit" in result.reason:
                status, key = "REJECTED_MAX_POSITIONS", "rejected_max_positions"
            elif "exposure" in result.reason:
                status, key = "REJECTED_EXPOSURE", "rejected_exposure"
            else:
                status, key = "REJECTED_POLICY", "rejected_policy"
            upsert_policy_decision(sid, policy.policy_version, status, result.reason)
            counts[key] += 1
            continue

        trade_id = create_paper_trade(result.trade)
        if trade_id is None:
            upsert_policy_decision(sid, policy.policy_version, "REJECTED_POLICY", "failed to persist paper trade")
            counts["rejected_policy"] += 1
            continue
        upsert_policy_decision(sid, policy.policy_version, "OPENED", "opened", trade_id=trade_id)
        counts["opened"] += 1
        open_trades = open_trades + [result.trade]
        open_symbols.add(signal["symbol"])

    return counts


def manage_open_positions(policy: Optional[PaperPolicy] = None, get_ohlcv_fn: Optional[Callable] = None) -> Dict[str, int]:
    """Apply T2's own deterministic simulate_exit() to every open trade —
    never rewrites that logic. A trade with no price data yet since entry
    stays open (simulate_exit returns None); once closed, fetch_paper_trades
    (status="open") will never return it again on a future run, which is
    what makes this idempotent without needing a status guard in the
    UPDATE itself."""
    policy = policy or PaperPolicy()
    if get_ohlcv_fn is None:
        from utils.market_data_provider import get_ohlcv as get_ohlcv_fn

    open_trades = fetch_paper_trades(status="open")
    closed_count = 0
    for trade in open_trades:
        try:
            hist = get_ohlcv_fn(trade["symbol"], "1y")
        except Exception:
            continue
        if hist is None or hist.empty:
            continue
        entry_date = str(trade["entry_timestamp"])[:10]
        price_path = []
        for ts, row in hist.iterrows():
            date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
            if date_str > entry_date:
                price_path.append({"date": date_str, "high": float(row["High"]),
                                    "low": float(row["Low"]), "close": float(row["Close"])})
        closed = simulate_exit(trade, price_path, policy.config)
        if closed is not None and close_paper_trade(trade["trade_id"], closed):
            closed_count += 1
    return {"closed": closed_count, "open_before": len(open_trades)}


def run_paper_portfolio(policy: Optional[PaperPolicy] = None, get_ohlcv_fn: Optional[Callable] = None) -> Dict[str, Any]:
    """The daily 'paper-portfolio run' — idempotent, safe to run any
    number of times per day. Manages existing positions first (so a
    just-closed symbol frees exposure/slot room before new entries are
    evaluated), then processes newly eligible signals."""
    policy = policy or PaperPolicy()
    open_before = len(fetch_paper_trades(status="open"))
    manage_result = manage_open_positions(policy, get_ohlcv_fn)
    entry_result = process_new_signals(policy, get_ohlcv_fn)
    open_after = len(fetch_paper_trades(status="open"))
    return {
        "policy_version": policy.policy_version,
        "open_before": open_before,
        "closed_today": manage_result["closed"],
        "new_eligible_signals": entry_result["considered"],
        "opened": entry_result["opened"],
        "rejected_exposure": entry_result["rejected_exposure"],
        "rejected_max_positions": entry_result["rejected_max_positions"],
        "rejected_duplicate_symbol": entry_result["rejected_duplicate_symbol"],
        "rejected_policy": entry_result["rejected_policy"],
        "invalid_signal": entry_result["invalid_signal"],
        "pending_entry": entry_result["pending_entry"],
        "open_after": open_after,
    }


def get_status(policy: Optional[PaperPolicy] = None) -> Dict[str, Any]:
    """Never fabricates a metric when data is unavailable — compute_metrics
    (T2) already reports None/0 for an empty closed-trade set."""
    policy = policy or PaperPolicy()
    open_trades = fetch_paper_trades(status="open")
    closed_trades = fetch_paper_trades(status="closed")
    metrics = compute_metrics(closed_trades)
    decisions = fetch_policy_decisions()
    by_status: Dict[str, int] = {}
    for d in decisions:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    return {
        "policy_version": policy.policy_version,
        "open_positions": len(open_trades),
        "closed_positions": len(closed_trades),
        **metrics,
        "signals_considered": len(decisions),
        "signals_by_decision": by_status,
    }


def _cli() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="FORTRESS-E2 automated paper portfolio")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "run":
        print(json.dumps(run_paper_portfolio(), indent=2, default=str))
    elif args.command == "status":
        print(json.dumps(get_status(), indent=2, default=str))


if __name__ == "__main__":
    _cli()
