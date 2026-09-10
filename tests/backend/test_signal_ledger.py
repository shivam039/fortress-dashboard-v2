"""FORTRESS-T1: immutable signal ledger tests.

signal_ledger is append-only — every record_signal_ledger_entries() call is
a plain INSERT, never an UPDATE/UPSERT (see utils/db.py's module note).
Exercised directly against SQLite (FORTRESS_DB_BACKEND=sqlite, set by
tests/conftest.py).
"""
from utils.db import fetch_signal_ledger, record_signal_ledger_entries


def _entry(**overrides):
    base = {
        "generated_at": "2026-01-15 10:00:00",
        "symbol": "ZZLEDGER1.NS",
        "sector": "IT",
        "score": 72.5,
        "component_scores": {"technical": 80.0, "fundamental": 60.0, "sentiment": 70.0, "context": 65.0},
        "market_regime": "Bull",
        "regime_multiplier": 1.1,
        "price_used": 2500.0,
        "data_source": "bhavcopy",
        "data_timestamp": "2026-01-14",
        "scan_id": 1,
        "scan_version": "v1",
        "universe": "Nifty 50",
        "explanation": "🚀 PASS — Momentum Pick",
        "suggested_entry": 2500.0,
        "stop_loss": 2450.0,
        "target": 2600.0,
        "risk_classification": "🚀 PASS",
        "feature_snapshot": {"Symbol": "ZZLEDGER1.NS", "RSI": 62.0, "Score": 72.5},
    }
    base.update(overrides)
    return base


# ── Creation ─────────────────────────────────────────────────────────────


def test_record_signal_ledger_entries_creates_rows():
    written = record_signal_ledger_entries([_entry()])
    assert written == 1

    rows = fetch_signal_ledger(symbol="ZZLEDGER1.NS", limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "ZZLEDGER1.NS"
    assert row["score"] == 72.5
    assert row["sector"] == "IT"
    assert row["market_regime"] == "Bull"
    assert row["data_source"] == "bhavcopy"
    assert row["scan_version"] == "v1"
    assert row["risk_classification"] == "🚀 PASS"
    # Point-in-time reconstruction payload round-trips as a real dict, not
    # a JSON string.
    assert row["component_scores"] == {"technical": 80.0, "fundamental": 60.0, "sentiment": 70.0, "context": 65.0}
    assert row["feature_snapshot"] == {"Symbol": "ZZLEDGER1.NS", "RSI": 62.0, "Score": 72.5}


def test_record_signal_ledger_entries_batches_multiple_symbols():
    written = record_signal_ledger_entries([
        _entry(symbol="ZZLEDGER2.NS", score=50.0),
        _entry(symbol="ZZLEDGER3.NS", score=90.0),
    ])
    assert written == 2

    rows2 = fetch_signal_ledger(symbol="ZZLEDGER2.NS")
    rows3 = fetch_signal_ledger(symbol="ZZLEDGER3.NS")
    assert rows2[0]["score"] == 50.0
    assert rows3[0]["score"] == 90.0


def test_record_signal_ledger_entries_empty_list_is_a_noop():
    assert record_signal_ledger_entries([]) == 0


# ── Duplicate handling: append, never overwrite ─────────────────────────


def test_duplicate_signal_creates_a_new_row_not_an_update():
    """Recording the exact same signal twice (e.g. a retried scan) must
    produce two distinct, independently-inspectable rows — the whole point
    of an append-only ledger is that nothing already written is ever
    overwritten, even by an identical observation."""
    entry = _entry(symbol="ZZLEDGERDUP.NS", score=55.0)

    record_signal_ledger_entries([entry])
    record_signal_ledger_entries([dict(entry)])  # identical payload again

    rows = fetch_signal_ledger(symbol="ZZLEDGERDUP.NS", limit=10)
    assert len(rows) == 2
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["score"] == rows[1]["score"] == 55.0


def test_re_scored_signal_does_not_touch_the_earlier_row():
    """A later scan that re-scores the same symbol differently must add a
    new row, and the earlier row's score must remain exactly as recorded —
    proving a current score change never rewrites history."""
    record_signal_ledger_entries([_entry(symbol="ZZLEDGERRESCAN.NS", score=40.0, scan_id=1)])
    record_signal_ledger_entries([_entry(symbol="ZZLEDGERRESCAN.NS", score=85.0, scan_id=2)])

    rows = fetch_signal_ledger(symbol="ZZLEDGERRESCAN.NS", limit=10)
    assert len(rows) == 2
    scores_by_scan = {r["scan_id"]: r["score"] for r in rows}
    assert scores_by_scan[1] == 40.0
    assert scores_by_scan[2] == 85.0


# ── Timestamp integrity ──────────────────────────────────────────────────


def test_generated_at_is_stored_verbatim_per_entry():
    record_signal_ledger_entries([
        _entry(symbol="ZZLEDGERTIME.NS", generated_at="2026-02-01 09:00:00", scan_id=10),
        _entry(symbol="ZZLEDGERTIME.NS", generated_at="2026-02-02 09:00:00", scan_id=11),
    ])
    rows = fetch_signal_ledger(symbol="ZZLEDGERTIME.NS", limit=10)
    generated_ats = sorted(r["generated_at"] for r in rows)
    assert generated_ats == ["2026-02-01 09:00:00", "2026-02-02 09:00:00"]


def test_missing_generated_at_defaults_to_a_timestamp_not_left_null():
    entry = _entry(symbol="ZZLEDGERNOTIME.NS")
    del entry["generated_at"]
    record_signal_ledger_entries([entry])

    rows = fetch_signal_ledger(symbol="ZZLEDGERNOTIME.NS")
    assert rows[0]["generated_at"]  # non-empty, defaulted rather than NULL


def test_created_at_is_independent_of_generated_at():
    """created_at (DB insert time) is a separate audit trail from
    generated_at (point-in-time signal generation) — both must be present."""
    record_signal_ledger_entries([_entry(symbol="ZZLEDGERAUDIT.NS", generated_at="2020-01-01 00:00:00")])
    row = fetch_signal_ledger(symbol="ZZLEDGERAUDIT.NS")[0]
    assert row["generated_at"] == "2020-01-01 00:00:00"
    assert row["created_at"]  # set by the DB at insert time, not backdated


# ── Source/version capture ──────────────────────────────────────────────


def test_data_source_and_scan_version_are_captured():
    record_signal_ledger_entries([_entry(symbol="ZZLEDGERSRC.NS", data_source="indstocks", scan_version="v2")])
    row = fetch_signal_ledger(symbol="ZZLEDGERSRC.NS")[0]
    assert row["data_source"] == "indstocks"
    assert row["scan_version"] == "v2"


def test_missing_data_source_is_stored_as_null_not_fabricated():
    entry = _entry(symbol="ZZLEDGERNOSRC.NS")
    entry["data_source"] = None
    record_signal_ledger_entries([entry])
    row = fetch_signal_ledger(symbol="ZZLEDGERNOSRC.NS")[0]
    assert row["data_source"] is None


# ── Persistence failures ─────────────────────────────────────────────────


def test_persistence_failure_is_swallowed_and_reports_zero_written(monkeypatch):
    """A DB error while writing the ledger must never raise into the
    caller (the scan whose signals it's recording must not fail because of
    it) — it should log and report 0 entries written instead."""
    from utils import db

    def raising_ensure(*_a, **_k):
        raise RuntimeError("simulated disk-full error")

    monkeypatch.setattr(db, "_ensure_signal_ledger_sqlite", raising_ensure)

    written = record_signal_ledger_entries([_entry(symbol="ZZLEDGERFAIL.NS")])
    assert written == 0

    # And the failure didn't leave a partial/corrupt row behind.
    monkeypatch.undo()
    assert fetch_signal_ledger(symbol="ZZLEDGERFAIL.NS") == []


def test_fetch_signal_ledger_swallows_read_errors(monkeypatch):
    from utils import db

    def raising_connection(*_a, **_k):
        raise RuntimeError("simulated connection error")

    monkeypatch.setattr(db, "_sqlite_connection", raising_connection)
    assert fetch_signal_ledger(symbol="ANY.NS") == []


def test_fetch_signal_ledger_unknown_symbol_returns_empty_list():
    assert fetch_signal_ledger(symbol="ZZNEVERRECORDED.NS") == []


# ── Integration: a real scan actually writes to the ledger ──────────────


def test_scan_writes_signal_ledger_entries_end_to_end(monkeypatch):
    """POST /api/scan (the real scan pipeline) must append a signal_ledger
    row per matched ticker — this is what makes a historical signal
    inspectable later without relying on today's state."""
    import main as main_mod
    import pandas as pd
    from fastapi.testclient import TestClient
    from main import app
    from utils.db import init_db

    # TestClient() without a `with` block skips FastAPI's startup event,
    # which is what creates the scans/scan_history_details tables in a real
    # run — same as test_api.py's history-persistence test.
    init_db()

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
    monkeypatch.setattr(
        main_mod,
        "check_institutional_fortress",
        lambda ticker, *a, **k: {"Symbol": ticker, "Price": 100.0, "Sector": "IT", "Data_As_Of": "2026-01-14"},
    )
    monkeypatch.setattr(
        main_mod, "apply_advanced_scoring",
        lambda df, cfg: df.assign(Score=77.0, Verdict="🚀 PASS", Strategy="Momentum Pick"),
    )

    payload = {"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01}
    response = client.post("/api/scan", json=payload)
    assert response.status_code == 200

    rows = fetch_signal_ledger(symbol="RELIANCE.NS", limit=5)
    assert len(rows) >= 1
    row = rows[0]
    assert row["score"] == 77.0
    assert row["sector"] == "IT"
    assert row["data_timestamp"] == "2026-01-14"
    assert row["scan_version"] == "v1"
    assert row["universe"] == "Nifty 50"
    assert row["risk_classification"] == "🚀 PASS"
    assert "Momentum Pick" in row["explanation"]
    # Full point-in-time snapshot present for later reconstruction.
    assert row["feature_snapshot"]["Symbol"] == "RELIANCE.NS"
