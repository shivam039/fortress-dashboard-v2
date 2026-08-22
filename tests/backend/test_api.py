import pandas as pd
from fastapi.testclient import TestClient

import engine.main as main_mod
from engine.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_market_data_status_reports_provider_and_universes():
    response = client.get("/api/market-data-status")
    assert response.status_code == 200
    body = response.json()
    assert body["primary"] in ("indstocks", "yfinance")
    assert body["primary_label"] in ("INDmoney", "Yahoo Finance")
    assert body["auth_mode"] in ("totp", "static_token", "none")
    assert "universes" in body
    assert body["universes"].get("Nifty 50", 0) > 0


def test_market_data_status_reflects_indstocks_when_configured(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token-for-status-test")
    response = client.get("/api/market-data-status")
    assert response.status_code == 200
    body = response.json()
    assert body["primary"] == "indstocks"
    assert body["primary_label"] == "INDmoney"
    assert body["auth_mode"] == "static_token"


def test_scan_prefetches_metadata_for_the_whole_universe_before_scoring(monkeypatch):
    """/api/scan must bulk-preload fundamental/news/calendar/earnings
    metadata for the whole universe before scoring individual tickers —
    this was missing entirely (only the legacy Streamlit UI did it), meaning
    every scan hit yfinance live for .info/.news/.calendar/.earnings_dates
    on every ticker, every time, with no cross-run caching."""
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })

    calls = {}

    def fake_prefetch(tickers):
        calls["tickers"] = list(tickers)

    monkeypatch.setattr(main_mod, "prefetch_metadata", fake_prefetch)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda *a, **k: None)

    payload = {"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01}
    response = client.post("/api/scan", json=payload)

    assert response.status_code == 200
    assert "tickers" in calls, "prefetch_metadata was never called"
    assert len(calls["tickers"]) == 50
    assert "RELIANCE.NS" in calls["tickers"]


def test_sector_pulse_prefetches_metadata_before_scoring(monkeypatch):
    calls = {}

    def fake_prefetch(tickers):
        calls["tickers"] = list(tickers)

    monkeypatch.setattr(main_mod, "prefetch_metadata", fake_prefetch)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda *a, **k: None)

    response = client.get("/api/sector-pulse", params={"universe": "Nifty 50"})

    assert response.status_code == 200
    assert "tickers" in calls, "prefetch_metadata was never called"
    assert len(calls["tickers"]) == 50


def test_trigger_mf_job(monkeypatch):
    def mock_run_mf_background_job(*args, **kwargs):
        pass

    import engine.main

    monkeypatch.setattr(
        engine.main, "run_mf_background_job", mock_run_mf_background_job
    )

    payload = {"job_type": "refresh_nav", "force_refresh": False, "scheme_codes": []}
    response = client.post("/mf/trigger-job", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
