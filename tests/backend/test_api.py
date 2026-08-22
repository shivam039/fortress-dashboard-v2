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


def test_scan_circuit_breaker_trips_on_high_failure_rate(monkeypatch):
    """If enough tickers fail in a row (provider outage, rate limiting),
    /api/scan should stop early and say so instead of grinding through the
    whole universe with no aggregate failure visibility — this was flagged
    as a missing circuit-breaker/retry-budget surface with no way for a
    caller to tell a real outage apart from "nothing matched the screen"."""
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)

    def fake_get_stock_data(*a, **k):
        # The bulk call is made with a tuple of all tickers as the first
        # positional arg; return it empty so run_scan falls back to the
        # per-ticker path below (a single ticker string as the first arg),
        # which needs >=210 rows to reach check_institutional_fortress at
        # all — otherwise the failure never happens and the breaker can't
        # trip.
        first_arg = a[0] if a else None
        if isinstance(first_arg, tuple):
            return pd.DataFrame()
        return pd.DataFrame({"Close": range(250)})

    monkeypatch.setattr(main_mod, "get_stock_data", fake_get_stock_data)

    def always_fails(*a, **k):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr(main_mod, "check_institutional_fortress", always_fails)

    payload = {"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01}
    response = client.post("/api/scan", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["circuit_breaker_tripped"] is True
    assert body["failed"] >= 10
    # Nifty 50 has 50 tickers — the breaker must stop well short of scanning
    # all of them once the failure rate crosses the threshold.
    assert body["scanned"] < 50
    assert "aborted early" in body["summary"].lower()


def test_scan_no_circuit_breaker_when_most_tickers_succeed(monkeypatch):
    """A normal scan with only occasional per-ticker failures (a couple of
    delisted symbols, say) must not trip the breaker or change response
    shape — this is the existing, common case and must keep working
    exactly as before."""
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame())

    call_count = {"n": 0}

    def mostly_succeeds(*a, **k):
        call_count["n"] += 1
        # Only fail the very first call — a 2% failure rate, nowhere near
        # the 80% breaker threshold.
        if call_count["n"] == 1:
            raise RuntimeError("one delisted ticker")
        return None  # no result, but not an error

    monkeypatch.setattr(main_mod, "check_institutional_fortress", mostly_succeeds)

    payload = {"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01}
    response = client.post("/api/scan", json=payload)

    assert response.status_code == 200
    body = response.json()
    # get_stock_data is mocked empty, and check_institutional_fortress never
    # returns a truthy result, so this ends up in the "no results" branch —
    # but circuit_breaker_tripped must be False since the failure rate (1/50)
    # never crossed the threshold.
    assert body["circuit_breaker_tripped"] is False
    assert body["scanned"] == 50


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
