"""FORTRESS-E1: prospective evidence collection tests.

Exercised directly against SQLite (FORTRESS_DB_BACKEND=sqlite, set by
tests/conftest.py). No live network access is used anywhere here —
maturation is tested with an injected fake OHLCV function.
"""
import pandas as pd
import pytest
from research.prospective_store import (
    build_observation_entries,
    collect_from_scan,
    export_r1,
    get_status,
    mature_pending_outcomes,
    observation_id_for,
)
from utils.db import (
    fetch_research_observations,
    fetch_research_outcomes,
    record_research_observations,
)


def _row(symbol, score=85.0, quality_gate_pass=True, **overrides):
    base = {
        "Symbol": symbol, "Score": score, "Technical_Score": 90, "Fundamental_Score": 70,
        "Sentiment_Score": 60, "Context_Score": 80, "Market_Regime": "Bull", "Sector": "IT",
        "Quality_Gate_Pass": quality_gate_pass, "Quality_Gate_Failures": "", "Price": 100.0, "RSI": 55,
    }
    base.update(overrides)
    return base


def _fake_hist(closes, start="2025-02-03"):
    dates = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=dates)


# ── 1/10/11. observation persistence, scoring version, unscorable never fabricated ──


def test_observation_persistence_and_scoring_version_and_criteria():
    r = collect_from_scan([_row("E1AAA.NS")], scan_id=1, trading_date="2025-02-03", scoring_version="e1t-v1")
    assert r == {"inserted": 1, "duplicates": 0}

    rows = fetch_research_observations(scoring_version="e1t-v1")
    obs = next(o for o in rows if o["symbol"] == "E1AAA.NS")
    assert obs["fortress_score"] == 85.0
    assert obs["scoring_version"] == "e1t-v1"
    assert obs["schema_version"]
    assert bool(obs["quality_gate_pass"]) is True
    assert bool(obs["passed_criteria"]) is True

    # Unscorable ticker: never build an entry with a fabricated score.
    entries = build_observation_entries([{"Symbol": None, "Score": 999}], None, "2025-02-03", "e1t-v1")
    assert entries == []  # no Symbol -> not a scoreable row, silently skipped, no score invented


# ── 2. duplicate ingestion idempotency ──


def test_duplicate_ingestion_is_idempotent():
    first = collect_from_scan([_row("E1BBB.NS")], scan_id=1, trading_date="2025-02-04", scoring_version="e1t-v1")
    second = collect_from_scan([_row("E1BBB.NS")], scan_id=2, trading_date="2025-02-04", scoring_version="e1t-v1")
    assert first == {"inserted": 1, "duplicates": 0}
    assert second == {"inserted": 0, "duplicates": 1}
    assert len([o for o in fetch_research_observations(scoring_version="e1t-v1") if o["symbol"] == "E1BBB.NS"]) == 1


# ── 3. next trading date creates a new observation; 20. mixed scoring versions ──


def test_new_trading_date_and_new_scoring_version_each_create_a_new_observation():
    collect_from_scan([_row("E1CCC.NS")], scan_id=1, trading_date="2025-02-05", scoring_version="e1t-v1")
    collect_from_scan([_row("E1CCC.NS")], scan_id=2, trading_date="2025-02-06", scoring_version="e1t-v1")
    collect_from_scan([_row("E1CCC.NS")], scan_id=3, trading_date="2025-02-05", scoring_version="e1t-v2")

    rows = [o for o in fetch_research_observations() if o["symbol"] == "E1CCC.NS"]
    keys = {(o["trading_date"], o["scoring_version"]) for o in rows}
    assert keys == {("2025-02-05", "e1t-v1"), ("2025-02-06", "e1t-v1"), ("2025-02-05", "e1t-v2")}
    assert len(rows) == 3  # distinct observations, none overwritten


# ── 4/5/6/8. outcomes start unavailable; 5D can't mature early; matures on the right session; horizons independent ──


def test_outcomes_start_not_yet_mature_then_5d_matures_others_dont():
    collect_from_scan([_row("E1DDD.NS")], scan_id=1, trading_date="2025-02-03", scoring_version="e1t-v1")
    outcomes = [o for o in fetch_research_outcomes() if o["observation_id"] == observation_id_for("2025-02-03", "E1DDD.NS", "e1t-v1")]
    assert {o["horizon"] for o in outcomes} == {5, 10, 20, 60}
    assert all(o["status"] == "NOT_YET_MATURE" for o in outcomes)

    # Only 6 future sessions exist (index 1..6) -> 5D (needs index 5) matures, 10/20/60 don't.
    closes = [100, 101, 102, 103, 104, 110, 106]
    result = mature_pending_outcomes(get_ohlcv_fn=lambda symbol, period: _fake_hist(closes))

    outcomes = [o for o in fetch_research_outcomes() if o["observation_id"] == observation_id_for("2025-02-03", "E1DDD.NS", "e1t-v1")]
    by_h = {o["horizon"]: o for o in outcomes}
    assert by_h[5]["status"] == "MATURED"
    assert by_h[5]["forward_return"] == pytest.approx(0.10)
    assert by_h[10]["status"] == "NOT_YET_MATURE"
    assert by_h[20]["status"] == "NOT_YET_MATURE"
    assert by_h[60]["status"] == "NOT_YET_MATURE"
    assert result["matured"] >= 1


# ── 7. missing price never becomes 0% ──


def test_missing_future_price_is_missing_data_not_zero_percent():
    collect_from_scan([_row("E1EEE.NS")], scan_id=1, trading_date="2025-02-03", scoring_version="e1t-v1")
    closes = [100, 101, 102, 103, 104, float("nan")]  # index 5 (5D target) is NaN
    mature_pending_outcomes(get_ohlcv_fn=lambda symbol, period: _fake_hist(closes))

    outcomes = [o for o in fetch_research_outcomes() if o["observation_id"] == observation_id_for("2025-02-03", "E1EEE.NS", "e1t-v1")]
    five_d = next(o for o in outcomes if o["horizon"] == 5)
    assert five_d["status"] == "MISSING_DATA"
    assert five_d["forward_return"] is None  # never 0.0


# ── 9/18. finalized outcome isn't silently rewritten; maturation rerun idempotent ──


def test_finalized_outcome_is_not_rewritten_on_rerun_with_different_prices():
    collect_from_scan([_row("E1FFF.NS")], scan_id=1, trading_date="2025-02-03", scoring_version="e1t-v1")
    mature_pending_outcomes(get_ohlcv_fn=lambda symbol, period: _fake_hist([100, 101, 102, 103, 104, 110, 106]))
    first = next(o for o in fetch_research_outcomes() if o["observation_id"] == observation_id_for("2025-02-03", "E1FFF.NS", "e1t-v1") and o["horizon"] == 5)
    assert first["forward_return"] == pytest.approx(0.10)

    # Rerun with a DIFFERENT (wrong/corrupted) price series — must not change the finalized row.
    mature_pending_outcomes(get_ohlcv_fn=lambda symbol, period: _fake_hist([100, 101, 102, 103, 104, 999, 106]))
    again = next(o for o in fetch_research_outcomes() if o["observation_id"] == observation_id_for("2025-02-03", "E1FFF.NS", "e1t-v1") and o["horizon"] == 5)
    assert again["forward_return"] == pytest.approx(0.10)  # unchanged


# ── 12. unscorable ticker isn't fabricated (build_observation_entries) ──


def test_unscorable_ticker_produces_no_observation():
    entries = build_observation_entries([_row("E1GGG.NS"), {"Symbol": None}], None, "2025-02-03", "e1t-v1")
    symbols = {e["symbol"] for e in entries}
    assert symbols == {"E1GGG.NS"}


# ── 13/14. research<->signal<->paper linkage via join key; observation without a paper trade ──


def test_research_observation_links_to_signal_via_scan_id_and_symbol_without_requiring_a_paper_trade():
    from utils.db import record_signal_ledger_entries

    scan_id = 4242
    collect_from_scan([_row("E1HHH.NS")], scan_id=scan_id, trading_date="2025-02-03", scoring_version="e1t-v1")
    record_signal_ledger_entries([{
        "generated_at": "2025-02-03 16:00:00", "symbol": "E1HHH.NS", "score": 85.0,
        "scan_id": scan_id, "feature_snapshot": {"Symbol": "E1HHH.NS"},
    }])

    from utils.db import fetch_signal_ledger
    obs = next(o for o in fetch_research_observations() if o["symbol"] == "E1HHH.NS" and o["scan_id"] == scan_id)
    signal = next(s for s in fetch_signal_ledger(symbol="E1HHH.NS") if s["scan_id"] == scan_id)
    assert obs["scan_id"] == signal["scan_id"]  # the join key that links them
    # No paper trade exists for this observation, and that's a valid state.


# ── 15/16. R1 export deterministic shape + accepted by existing R2 ──


def test_r1_export_shape_and_r2_accepts_it(tmp_path):
    collect_from_scan([_row("E1III.NS")], scan_id=1, trading_date="2025-02-03", scoring_version="e1t-export")
    mature_pending_outcomes(get_ohlcv_fn=lambda symbol, period: _fake_hist([100, 101, 102, 103, 104, 110, 106]))

    out = tmp_path / "r1_export.sqlite"
    result = export_r1(str(out))
    assert result["observation_count"] >= 1
    assert out.exists()

    with pytest.raises(FileExistsError):
        export_r1(str(out))  # re-exporting to the same path is refused, not silently overwritten

    from research.forward_return_validation import run_forward_return_validation
    report = run_forward_return_validation(str(out))
    assert report.total_labeled_pairs >= 1
    metrics = report.overall_bucket_metrics.get(5, {}).get("80-89")
    assert metrics is not None and metrics.sample_size >= 1


# ── 17. insufficient sample labelled correctly ──


def test_status_labels_small_sample_as_insufficient():
    collect_from_scan([_row("E1JJJ.NS")], scan_id=1, trading_date="2025-02-03", scoring_version="e1t-status")
    mature_pending_outcomes(get_ohlcv_fn=lambda symbol, period: _fake_hist([100, 101, 102, 103, 104, 110, 106]))
    status = get_status()
    cell = next(c for c in status["bucket_horizon_readiness"] if c["bucket"] == "80-89" and c["horizon"] == 5)
    assert cell["n"] < 20
    assert cell["status"] == "INSUFFICIENT_SAMPLE"


# ── 19. failed/circuit-broken scan doesn't generate misleading evidence ──


def test_record_research_observations_empty_entries_is_a_noop():
    assert record_research_observations([]) == {"inserted": 0, "duplicates": 0}


def test_circuit_breaker_tripped_scan_creates_no_research_observations(monkeypatch):
    """End-to-end through the real /api/scan path (identical setup to
    test_api.py::test_scan_circuit_breaker_trips_on_high_failure_rate): a
    provider outage fails every ticker and trips the breaker. Zero
    research_observations rows may exist afterward — a provider-outage
    scan must never look like valid evidence, even though scan_history/
    signal_ledger persistence (existing behavior) is unaffected by this
    story."""
    import main as main_mod
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)

    def fake_get_stock_data(*a, **k):
        first_arg = a[0] if a else None
        if isinstance(first_arg, tuple):
            return pd.DataFrame()
        return pd.DataFrame({"Close": range(250)})

    monkeypatch.setattr(main_mod, "get_stock_data", fake_get_stock_data)
    monkeypatch.setattr(main_mod, "check_institutional_fortress",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated provider outage")))

    before = len(fetch_research_observations())
    response = client.post("/api/scan", json={"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01})
    body = response.json()
    assert body["circuit_breaker_tripped"] is True
    assert len(fetch_research_observations()) == before, (
        "a circuit-breaker-tripped scan must not create research observations"
    )
