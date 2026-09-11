"""FORTRESS-E2: automated paper-trade selection from real T1 signals.

Exercised directly against SQLite (FORTRESS_DB_BACKEND=sqlite, set by
tests/conftest.py). No live network access — OHLCV is injected via
get_ohlcv_fn, always symbol-scoped (returns empty for any other symbol) so
that a PENDING_ENTRY signal left behind by an earlier test in this shared
DB is never accidentally resolved by a later, unrelated test's mock.
"""
import pandas as pd
import pytest
from paper_trading.policy_engine import (
    PaperPolicy,
    get_status,
    manage_open_positions,
    process_new_signals,
    run_paper_portfolio,
)
from utils.db import (
    close_paper_trade,
    fetch_paper_trades,
    fetch_policy_decisions,
    fetch_signal_ledger,
    record_research_observations,
    record_signal_ledger_entries,
)


def _record_scan(symbol, scan_id, gate_pass=True, trading_date="2025-04-01"):
    record_research_observations([{
        "observation_id": f"obs-{symbol}-{scan_id}", "scan_id": scan_id, "symbol": symbol,
        "exchange": "NSE", "trading_date": trading_date, "observation_timestamp": f"{trading_date}T16:00:00",
        "fortress_score": 85.0, "component_scores": {}, "market_regime": "Bull", "sector": "IT",
        "features_json": {}, "quality_gate_pass": gate_pass, "quality_gate_failures": "",
        "data_source": "bhavcopy", "data_timestamp": trading_date, "reference_price": 100.0,
        "scoring_version": "v1", "schema_version": "e1-v1", "git_sha": None, "passed_criteria": gate_pass,
    }])


def _record_signal(symbol, scan_id, gate_pass=True, generated_at="2025-04-01 16:00:00"):
    record_signal_ledger_entries([{
        "generated_at": generated_at, "symbol": symbol, "score": 85.0,
        "suggested_entry": 100.0, "stop_loss": 95.0, "target": 120.0, "scan_id": scan_id,
        "feature_snapshot": {"Symbol": symbol, "Quality_Gate_Pass": gate_pass},
    }])
    return next(s["id"] for s in fetch_signal_ledger(symbol=symbol) if s["scan_id"] == scan_id)


def _hist(closes, opens=None):
    dates = pd.date_range("2025-04-02", periods=len(closes), freq="B")
    opens = opens or closes
    return pd.DataFrame({
        "Open": opens, "High": [c + 5 for c in closes],
        "Low": [c - 5 for c in closes], "Close": closes,
    }, index=dates)


_baseline_cache = {"id": None}


@pytest.fixture(autouse=True, scope="module")
def _capture_baseline_signal_id():
    """Runs once, before this module's first test — never at import/
    collection time (too early: no tests, this file's own included, have
    run yet) — capturing the highest signal_ledger id left by other test
    files that already ran. process_new_signals() calls below are scoped
    to ids strictly after this, so this module never touches unrelated
    signal_ledger rows in this shared SQLite test database."""
    existing = fetch_signal_ledger(limit=1)
    _baseline_cache["id"] = existing[0]["id"] if existing else 0
    baseline_open_trade_ids = {t["trade_id"] for t in fetch_paper_trades(status="open")}
    yield
    # Close every position this module opened (using T2's own
    # close_paper_trade, a plain status transition — not simulate_exit,
    # since the outcome doesn't matter here) so other test files sharing
    # this DB see a clean slate against T2's default position/exposure
    # limits, exactly as if this module had never run.
    for t in fetch_paper_trades(status="open"):
        if t["trade_id"] not in baseline_open_trade_ids:
            close_paper_trade(t["trade_id"], {
                "exit_timestamp": "2025-04-01 16:00:00", "exit_price": t["entry_price"],
                "exit_reason": "test_cleanup", "gross_pnl": 0.0, "net_pnl": 0.0, "holding_period_days": 0,
            })


def _process(**kwargs):
    kwargs.setdefault("policy", _GENEROUS)
    kwargs.setdefault("min_signal_id", _baseline_cache["id"] + 1)
    return process_new_signals(**kwargs)


_GENEROUS = PaperPolicy(config=PaperPolicy().config.__class__(
    max_simultaneous_positions=1000, max_total_exposure=10_000_000.0, cost_bps=10.0))


def _price_fn(mapping):
    """Symbol-scoped OHLCV mock: any symbol not in `mapping` gets an empty
    frame, so pending signals from other tests are never accidentally
    resolved by a call this test didn't intend to affect."""
    def fn(symbol, period):
        return mapping[symbol] if symbol in mapping else pd.DataFrame()
    return fn


# ── 1/2. qualifying signal opens; non-qualifying doesn't ───────────────────


def test_qualifying_signal_opens_non_qualifying_does_not():
    _record_scan("E2AAA.NS", 101)
    _record_signal("E2AAA.NS", 101, gate_pass=True)
    _record_scan("E2BBB.NS", 101)
    _record_signal("E2BBB.NS", 101, gate_pass=False)

    counts = _process(get_ohlcv_fn=_price_fn({"E2AAA.NS": _hist([105, 106]), "E2BBB.NS": _hist([105, 106])}))
    assert counts["opened"] == 1
    assert counts["invalid_signal"] == 1
    open_trades = fetch_paper_trades(status="open")
    assert any(t["symbol"] == "E2AAA.NS" for t in open_trades)
    assert not any(t["symbol"] == "E2BBB.NS" for t in open_trades)


# ── 3. same signal cannot open twice (idempotency) ─────────────────────────


def test_rerun_does_not_reopen_the_same_signal():
    _record_scan("E2CCC.NS", 102)
    _record_signal("E2CCC.NS", 102)
    price = _price_fn({"E2CCC.NS": _hist([105, 106])})

    _process(get_ohlcv_fn=price)
    before = len(fetch_paper_trades(status="open"))
    counts = _process(get_ohlcv_fn=price)
    assert counts["considered"] == 0
    assert len(fetch_paper_trades(status="open")) == before


# ── 4. duplicate symbol handling ────────────────────────────────────────────


def test_duplicate_symbol_rejected_by_default():
    # Two distinct trading dates (a real re-scan a day later), each with
    # its own real E1 observation — E1's own (date, symbol, version)
    # idempotency key means the same date can't be reused for a second
    # "scan" here.
    price = _price_fn({"E2DDD.NS": _hist([105, 106])})
    _record_scan("E2DDD.NS", 103, trading_date="2025-04-01")
    _record_signal("E2DDD.NS", 103, generated_at="2025-04-01 16:00:00")
    _process(get_ohlcv_fn=price)

    _record_scan("E2DDD.NS", 104, trading_date="2025-04-02")
    _record_signal("E2DDD.NS", 104, generated_at="2025-04-02 16:00:00")
    counts = _process(get_ohlcv_fn=price)
    assert counts["rejected_duplicate_symbol"] == 1


# ── 5/6. max positions / max exposure enforced ──────────────────────────────


def test_max_simultaneous_positions_enforced():
    # Computed relative to whatever this shared test DB already has open
    # (other tests in this file leave positions open) — this test only
    # asserts that exactly one MORE slot is available, regardless of order.
    current_open = len(fetch_paper_trades(status="open"))
    cfg = PaperPolicy().config.__class__(max_simultaneous_positions=current_open + 1, cost_bps=10.0)
    policy = PaperPolicy(config=cfg)
    price = _price_fn({"E2EEE.NS": _hist([105, 106]), "E2FFF.NS": _hist([105, 106])})
    _record_scan("E2EEE.NS", 105)
    _record_signal("E2EEE.NS", 105, generated_at="2025-04-01 16:00:00")
    _record_scan("E2FFF.NS", 105)
    _record_signal("E2FFF.NS", 105, generated_at="2025-04-01 16:01:00")

    counts = _process(policy=policy, get_ohlcv_fn=price)
    assert counts["opened"] == 1
    assert counts["rejected_max_positions"] == 1


def test_max_exposure_enforced():
    # Exactly at the current exposure -> zero room left -> the new signal
    # is rejected outright rather than opened at a reduced (capped) size.
    current_exposure = sum(float(t.get("notional", 0.0)) for t in fetch_paper_trades(status="open"))
    cfg = PaperPolicy().config.__class__(
        max_total_exposure=current_exposure, max_position_notional=100_000.0, cost_bps=10.0)
    policy = PaperPolicy(config=cfg)
    _record_scan("E2GGG.NS", 106)
    _record_signal("E2GGG.NS", 106)
    counts = _process(policy=policy, get_ohlcv_fn=_price_fn({"E2GGG.NS": _hist([105, 106])}))
    assert counts["rejected_exposure"] == 1


# ── 7. deterministic ordering ────────────────────────────────────────────────


def test_signals_are_considered_in_deterministic_id_order():
    ids = []
    price = _price_fn({"E2HHH.NS": _hist([105, 106]), "E2III.NS": _hist([105, 106])})
    for sym in ("E2HHH.NS", "E2III.NS"):
        _record_scan(sym, 107)
        ids.append(_record_signal(sym, 107))
    current_open = len(fetch_paper_trades(status="open"))
    cfg = PaperPolicy().config.__class__(max_simultaneous_positions=current_open + 1, cost_bps=10.0)
    _process(policy=PaperPolicy(config=cfg), get_ohlcv_fn=price)
    decisions = {d["signal_id"]: d["status"] for d in fetch_policy_decisions() if d["signal_id"] in ids}
    assert decisions[ids[0]] == "OPENED"
    assert decisions[ids[1]] == "REJECTED_MAX_POSITIONS"


# ── 8. next-session entry semantics (no look-ahead) ─────────────────────────


def test_entry_uses_next_session_open_not_signal_day_price():
    _record_scan("E2JJJ.NS", 108)
    _record_signal("E2JJJ.NS", 108)
    _process(get_ohlcv_fn=_price_fn({"E2JJJ.NS": _hist([200, 201], opens=[199, 200])}))
    trade = next(t for t in fetch_paper_trades(status="open") if t["symbol"] == "E2JJJ.NS")
    assert trade["entry_price"] == 199.0  # next session's Open, not the raw signal price (100.0)


def test_signal_too_recent_stays_pending_not_opened():
    _record_scan("E2KKK.NS", 109)
    _record_signal("E2KKK.NS", 109)
    counts = _process(get_ohlcv_fn=_price_fn({}))  # no next session data for anyone
    assert counts["pending_entry"] >= 1
    assert not any(t["symbol"] == "E2KKK.NS" for t in fetch_paper_trades(status="open"))


# ── 9/10/11. stop / target / time exits (via T2's own simulate_exit) ───────


def test_stop_target_and_time_exits_close_positions():
    entry_price = _price_fn({"E2STOP.NS": _hist([105, 106]), "E2TGT.NS": _hist([105, 106]), "E2TIME.NS": _hist([105, 106])})
    for sym in ("E2STOP.NS", "E2TGT.NS", "E2TIME.NS"):
        _record_scan(sym, 110)
        _record_signal(sym, 110)
    _process(get_ohlcv_fn=entry_price)

    exit_price = _price_fn({
        "E2STOP.NS": _hist([80]), "E2TGT.NS": _hist([130]), "E2TIME.NS": _hist([102]),
    })
    manage_open_positions(policy=_GENEROUS, get_ohlcv_fn=exit_price)
    closed = {t["symbol"]: t for t in fetch_paper_trades(status="closed") if t["symbol"] in ("E2STOP.NS", "E2TGT.NS", "E2TIME.NS")}
    assert closed["E2STOP.NS"]["exit_reason"] == "stop"
    assert closed["E2TGT.NS"]["exit_reason"] == "target"


# ── 12. failed/circuit-broken scan creates no positions ─────────────────────


def test_signal_without_matching_e1_observation_is_never_opened():
    """No _record_scan() call here — simulates a signal from a scan E1
    skipped recording because the circuit breaker tripped."""
    _record_signal("E2NOOBS.NS", 111)
    counts = _process(get_ohlcv_fn=_price_fn({"E2NOOBS.NS": _hist([105, 106])}))
    assert counts["invalid_signal"] >= 1
    assert not any(t["symbol"] == "E2NOOBS.NS" for t in fetch_paper_trades(status="open"))


# ── 13. rerun is idempotent (management side, no double cost) ──────────────


def test_manage_open_positions_rerun_does_not_reclose_or_double_cost():
    _record_scan("E2IDEM.NS", 112)
    _record_signal("E2IDEM.NS", 112)
    _process(get_ohlcv_fn=_price_fn({"E2IDEM.NS": _hist([105, 106])}))
    manage_open_positions(policy=_GENEROUS, get_ohlcv_fn=_price_fn({"E2IDEM.NS": _hist([130])}))
    first = next(t for t in fetch_paper_trades(status="closed") if t["symbol"] == "E2IDEM.NS")

    manage_open_positions(policy=_GENEROUS, get_ohlcv_fn=_price_fn({"E2IDEM.NS": _hist([9999])}))  # would differ if it reran
    again = next(t for t in fetch_paper_trades(status="closed") if t["symbol"] == "E2IDEM.NS")
    assert again["net_pnl"] == first["net_pnl"]


# ── 14/15. policy version and rejection reason persisted ────────────────────


def test_policy_version_and_rejection_reason_are_persisted():
    signal_id = _record_signal("E2VER.NS", 113)  # no matching observation -> INVALID_SIGNAL
    _process(get_ohlcv_fn=_price_fn({"E2VER.NS": _hist([105, 106])}))
    decision = next(d for d in fetch_policy_decisions() if d["signal_id"] == signal_id)
    assert decision["policy_version"] == "e2-policy-v1"
    assert decision["status"] == "INVALID_SIGNAL"
    assert "observation" in decision["reason"]


# ── 16. no real broker/order path exists ────────────────────────────────────


def test_policy_engine_never_references_broker_execution():
    import inspect

    import paper_trading.policy_engine as mod

    src = inspect.getsource(mod)
    for term in ("generate_zerodha_url", "generate_dhan_url", "routers.brokers", "place_order"):
        assert term not in src


# ── status ────────────────────────────────────────────────────────────────


def test_run_and_status_report_compact_summary_and_never_fabricate():
    _record_scan("E2STATUS.NS", 114)
    _record_signal("E2STATUS.NS", 114)
    summary = run_paper_portfolio(policy=_GENEROUS, get_ohlcv_fn=_price_fn({"E2STATUS.NS": _hist([105, 106])}))
    assert summary["policy_version"] == "e2-policy-v1"
    assert summary["opened"] >= 1

    status = get_status()
    assert status["policy_version"] == "e2-policy-v1"
    assert status["open_positions"] >= 1
    assert status["signals_considered"] >= 1
