"""FORTRESS-V4: compact end-to-end verification of the full required chain,
through the real application (real FastAPI app, real async job endpoints,
real DB, real T1/E1/T2 code) with only the market-data provider boundary
mocked (no live network access in this suite):

  ASYNC SCAN -> JOB STATUS -> RESULTS -> RESEARCH OBSERVATIONS -> SIGNAL
  -> PAPER POSITION

Secure production config / app startup and the total-outage circuit-
breaker path are verified separately (test_database_fail_closed.py,
test_circuit_breaker_empty_data.py) and via a live subprocess boot
documented in docs/TRADE_READINESS_V4.md.
"""
import time

import main as main_mod
import pandas as pd
from auth_utils import get_current_user
from fastapi.testclient import TestClient
from main import app
from utils.db import fetch_research_observations, fetch_signal_ledger

app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user"}
client = TestClient(app)


def _wait_for_terminal(job_id, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/scan/jobs/{job_id}/status").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise TimeoutError("scan job did not reach a terminal state in time")


def test_full_chain_async_scan_to_paper_position(monkeypatch):
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)
    monkeypatch.setattr(main_mod, "TICKER_GROUPS", {"V4E2E Universe": ["ZZV4E2E.NS"]})
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame({"Close": range(250)}))
    monkeypatch.setattr(main_mod, "apply_advanced_scoring", lambda df, config: df)
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda ticker, *a, **k: {
        "Symbol": ticker, "Score": 88.0, "Quality_Gate_Pass": True, "Price": 250.0,
        "Technical_Score": 85, "Fundamental_Score": 80, "Sentiment_Score": 70, "Context_Score": 75,
        "Market_Regime": "Range", "Sector": "IT",
    })

    # ASYNC SCAN
    create_resp = client.post("/api/scan/jobs", json={"universe": "V4E2E Universe", "portfolio_val": 1000000, "risk_pct": 0.01})
    assert create_resp.status_code == 202
    job_id = create_resp.json()["job_id"]

    # JOB STATUS
    status_body = _wait_for_terminal(job_id)
    assert status_body["status"] == "completed"

    # RESULTS
    results = client.get(f"/api/scan/jobs/{job_id}/results").json()
    assert isinstance(results, list) and len(results) == 1
    assert results[0]["Symbol"] == "ZZV4E2E.NS"

    # RESEARCH OBSERVATIONS (FORTRESS-E1)
    observations = [o for o in fetch_research_observations() if o["symbol"] == "ZZV4E2E.NS"]
    assert len(observations) == 1
    assert observations[0]["fortress_score"] == 88.0

    # SIGNAL (FORTRESS-T1)
    signals = fetch_signal_ledger(symbol="ZZV4E2E.NS", limit=1)
    assert len(signals) == 1
    signal_id = signals[0]["id"]

    # PAPER POSITION (FORTRESS-T2, via the new router)
    opened = client.post("/api/paper-trades", json={"signal_id": signal_id})
    assert opened.status_code == 201
    body = opened.json()
    assert body["label"] == "PAPER TRADE"
    assert body["symbol"] == "ZZV4E2E.NS"
    assert body["entry_price"] == 250.0
