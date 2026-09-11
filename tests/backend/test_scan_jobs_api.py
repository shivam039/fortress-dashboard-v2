"""FORTRESS-P3: async scan job tests.

Covers:
  - execute_scan() reports progress through every required real stage
    (universe, metadata, market_data, indicators, scoring, persistence).
  - POST /api/scan/jobs -> GET .../status -> GET .../results, success path,
    with results byte-compatible with the synchronous POST /api/scan shape.
  - Failure path: a job that raises is visible as status="failed" with an
    error, not left stuck or silently swallowed.
  - 404 for an unknown job_id; 202 "not ready" for a job still in flight.

No live INDstocks/yfinance/DB network access — market data, metadata
prefetch, and scoring are mocked, same pattern as test_api.py.
"""
import asyncio
import logging
import time

import main as main_mod
import pandas as pd
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _wait_for_terminal_status(job_id, timeout_s=5.0):
    """Poll GET .../status until status is completed/failed. FastAPI's
    TestClient drives BackgroundTasks to completion before the POST call
    even returns, so in practice the very first poll already sees the
    terminal state — this loop just makes the test robust either way."""
    deadline = time.monotonic() + timeout_s
    body = None
    while time.monotonic() < deadline:
        resp = client.get(f"/api/scan/jobs/{job_id}/status")
        body = resp.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached a terminal status: {body}")


def _regime_patch():
    return {"Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0}


def test_execute_scan_reports_all_required_stages(monkeypatch):
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", _regime_patch)
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)

    def fake_get_stock_data(*a, **k):
        first_arg = a[0] if a else None
        if isinstance(first_arg, tuple):
            return pd.DataFrame()
        return pd.DataFrame({"Close": range(250)})

    monkeypatch.setattr(main_mod, "get_stock_data", fake_get_stock_data)
    # At least one ticker must "match" so the scan reaches the
    # scoring/persistence stages (an all-None scan short-circuits before
    # them, same as the pre-P3 synchronous endpoint always did).
    monkeypatch.setattr(
        main_mod,
        "check_institutional_fortress",
        lambda ticker, *a, **k: {"Symbol": ticker, "Price": 100.0},
    )
    monkeypatch.setattr(
        main_mod, "apply_advanced_scoring", lambda df, cfg: df.assign(Score=90.0)
    )

    events = []

    def recorder(stage, current=None, total=None, message=None):
        events.append((stage, current, total, message))

    req = main_mod.ScanRequest(universe="Nifty 50", portfolio_val=1_000_000, risk_pct=0.01)
    main_mod.execute_scan(req, progress_cb=recorder)

    stages_seen = [e[0] for e in events]
    for required_stage in ("universe", "metadata", "market_data", "indicators", "scoring", "persistence"):
        assert required_stage in stages_seen, f"missing progress stage: {required_stage}"

    # Order matters: universe first, indicators before scoring, scoring before persistence.
    assert stages_seen.index("universe") < stages_seen.index("metadata")
    assert stages_seen.index("metadata") < stages_seen.index("market_data")
    assert stages_seen.index("market_data") < stages_seen.index("indicators")
    assert stages_seen.index("indicators") < stages_seen.index("scoring")
    assert stages_seen.index("scoring") < stages_seen.index("persistence")

    # The final "indicators" progress event should report full completion.
    indicator_events = [e for e in events if e[0] == "indicators" and e[1] is not None]
    last_current, last_total = indicator_events[-1][1], indicator_events[-1][2]
    assert last_current == last_total == 50


def test_execute_scan_progress_is_noop_safe_without_callback(monkeypatch):
    """The synchronous POST /api/scan route calls execute_scan() with no
    progress_cb at all — must not raise. Real (non-empty, >=210 row) market
    data throughout: this test is about progress_cb safety across the full
    universe, not the circuit breaker (FORTRESS-V4's fix correctly trips
    the breaker on all-empty data, which would stop this scan at 10/50 —
    see test_circuit_breaker_empty_data.py for that behavior)."""
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", _regime_patch)
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame({"Close": range(250)}))
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda *a, **k: None)

    req = main_mod.ScanRequest(universe="Nifty 50", portfolio_val=1_000_000, risk_pct=0.01)
    result = main_mod.execute_scan(req)
    assert result["scanned"] == 50


def test_scan_job_success_end_to_end(monkeypatch):
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", _regime_patch)
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
        lambda ticker, *a, **k: {"Symbol": ticker, "Price": 100.0},
    )
    monkeypatch.setattr(
        main_mod, "apply_advanced_scoring", lambda df, cfg: df.assign(Score=90.0)
    )

    payload = {"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01}
    create_resp = client.post("/api/scan/jobs", json=payload)
    assert create_resp.status_code == 202
    body = create_resp.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    job_id = body["job_id"]

    status_body = _wait_for_terminal_status(job_id)
    assert status_body["status"] == "completed"
    assert status_body["stage"] == "completed"
    assert status_body["progress"]["current"] == status_body["progress"]["total"]
    assert status_body["universe"] == "Nifty 50"
    assert status_body["error"] is None

    results_resp = client.get(f"/api/scan/jobs/{job_id}/results")
    assert results_resp.status_code == 200
    results = results_resp.json()
    assert isinstance(results, list)
    assert len(results) == 50
    assert results[0]["Symbol"].endswith(".NS")

    # Byte-compatible with the synchronous endpoint's own response for the
    # same mocked inputs.
    sync_resp = client.post("/api/scan", json=payload)
    assert sync_resp.status_code == 200
    assert sync_resp.json() == results


def test_scan_job_failure_is_visible(monkeypatch):
    """A job whose scoring step raises must end up status='failed' with a
    visible error — never stuck in queued/running, never silently dropped."""
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", _regime_patch)
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
        lambda ticker, *a, **k: {"Symbol": ticker, "Price": 100.0},
    )

    def raise_scoring_bug(df, cfg):
        raise RuntimeError("simulated scoring crash")

    monkeypatch.setattr(main_mod, "apply_advanced_scoring", raise_scoring_bug)

    payload = {"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01}
    create_resp = client.post("/api/scan/jobs", json=payload)
    job_id = create_resp.json()["job_id"]

    status_body = _wait_for_terminal_status(job_id)
    assert status_body["status"] == "failed"
    assert status_body["error"]
    assert "simulated scoring crash" in status_body["error"]

    results_resp = client.get(f"/api/scan/jobs/{job_id}/results")
    assert results_resp.status_code == 200
    results_body = results_resp.json()
    assert results_body["status"] == "failed"
    assert "simulated scoring crash" in results_body["error"]


def test_scan_job_heartbeat_stops_after_completion(monkeypatch):
    calls = []

    def fake_execute(req, progress_cb, **kwargs):
        time.sleep(0.06)
        return []

    monkeypatch.setenv("FORTRESS_SCAN_JOB_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setattr(main_mod, "execute_scan", fake_execute)
    monkeypatch.setattr(main_mod, "heartbeat_scan_job", lambda job_id: calls.append(job_id) or 1)

    job_id = "job-heartbeat-lifecycle"
    from utils.db import create_scan_job

    create_scan_job(job_id, "Nifty 50", {})
    asyncio.run(main_mod._run_scan_job(job_id, main_mod.ScanRequest(universe="Nifty 50")))
    call_count = len(calls)
    time.sleep(0.03)

    assert call_count >= 1
    assert len(calls) == call_count


def test_scan_job_heartbeat_stops_after_failure(monkeypatch):
    calls = []

    def fake_execute(req, progress_cb, **kwargs):
        time.sleep(0.06)
        raise RuntimeError("simulated worker failure")

    monkeypatch.setenv("FORTRESS_SCAN_JOB_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setattr(main_mod, "execute_scan", fake_execute)
    monkeypatch.setattr(main_mod, "heartbeat_scan_job", lambda job_id: calls.append(job_id) or 1)

    job_id = "job-heartbeat-failure"
    from utils.db import create_scan_job, get_scan_job

    create_scan_job(job_id, "Nifty 50", {})
    asyncio.run(main_mod._run_scan_job(job_id, main_mod.ScanRequest(universe="Nifty 50")))
    call_count = len(calls)
    time.sleep(0.03)

    assert call_count >= 1
    assert len(calls) == call_count
    assert get_scan_job(job_id)["status"] == "failed"


def test_rss_telemetry_failure_is_nonfatal(monkeypatch):
    def raise_memory_error(_):
        raise OSError("rss unavailable")

    monkeypatch.setattr(main_mod.resource, "getrusage", raise_memory_error)
    assert main_mod._get_process_rss_mb() is None


def test_stage_log_contains_job_stage_duration_and_rss(caplog):
    with caplog.at_level(logging.INFO, logger="fortress-api"):
        main_mod._log_scan_stage("job-observe-1", "market_data", time.monotonic() - 0.01)

    assert any(
        "scan_stage job=job-observe-1 stage=market_data" in record.message
        and "duration_s=" in record.message
        and "rss_mb=" in record.message
        for record in caplog.records
    )


def test_scan_job_status_unknown_job_id_returns_404():
    resp = client.get("/api/scan/jobs/does-not-exist/status")
    assert resp.status_code == 404


def test_scan_job_results_unknown_job_id_returns_404():
    resp = client.get("/api/scan/jobs/does-not-exist/results")
    assert resp.status_code == 404


def test_scan_job_results_not_ready_returns_202(monkeypatch):
    """A job still queued/running must report "not ready" (202), not be
    confused with a real (possibly empty) result set."""
    from utils.db import create_scan_job

    job_id = "job-not-ready-test"
    create_scan_job(job_id, "Nifty 50", {"universe": "Nifty 50"})

    resp = client.get(f"/api/scan/jobs/{job_id}/results")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert "progress" in body


def test_scan_job_unknown_universe_returns_404():
    payload = {"universe": "Not A Real Universe", "portfolio_val": 1000000, "risk_pct": 0.01}
    resp = client.post("/api/scan/jobs", json=payload)
    assert resp.status_code == 404
