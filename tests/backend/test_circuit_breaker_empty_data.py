"""FORTRESS-V4 / Blocker B: silent empty-market-data circuit-breaker fix.

V3 found that a total provider outage (every ticker's OHLCV fetch returns
empty data, not an exception) reported "failed": 0 and
"circuit_breaker_tripped": false, because only thrown exceptions were
counted as failures. These tests reproduce that exact scenario and confirm
the fix, and confirm a legitimate real-data scoring rejection is still
never counted as a provider failure. No live network access is used —
`main_mod.get_stock_data` is mocked at the same boundary the existing
circuit-breaker tests already mock.
"""
import main as main_mod
import pandas as pd
from fastapi.testclient import TestClient
from main import app
from utils.db import fetch_research_observations

client = TestClient(app)


def _quiet_regime(monkeypatch):
    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)


# ── 7/8. empty (not exception) market data counts as failure and trips the breaker ──


def test_total_empty_data_outage_counts_as_failure_and_trips_breaker(monkeypatch):
    """Reproduces V3's exact finding: every ticker's fetch returns an empty
    DataFrame (no exception at all) — this must count toward the breaker
    and trip it, not silently report failed=0."""
    _quiet_regime(monkeypatch)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame())

    calls = {"n": 0}

    def count_calls(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(main_mod, "check_institutional_fortress", count_calls)

    response = client.post("/api/scan", json={"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01})
    assert response.status_code == 200
    body = response.json()
    assert body["circuit_breaker_tripped"] is True
    assert body["failed"] >= 10  # not 0 — this is the bug V3 found
    assert body["scanned"] < 50  # aborted early, did not grind through the whole universe
    assert calls["n"] == 0  # never even attempted scoring on unusable data


# ── 9. a legitimate real-data scoring rejection is never counted as a provider failure ──


def test_real_data_rejected_by_scoring_is_not_counted_as_provider_failure(monkeypatch):
    """A ticker with genuinely sufficient market data that check_institutional_
    fortress legitimately screens out (e.g. the smallcap liquidity guard) is
    a real scoring outcome, not a data problem — must never move the
    failure count or trip the breaker."""
    _quiet_regime(monkeypatch)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame({"Close": range(250)}))
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda *a, **k: None)  # legitimate rejection

    response = client.post("/api/scan", json={"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01})
    assert response.status_code == 200
    body = response.json()
    assert body["circuit_breaker_tripped"] is False
    assert body["failed"] == 0
    assert body["scanned"] == 50


# ── 10/11. E1 integration: circuit-broken scans produce no observations; normal scans do ──


def test_empty_data_circuit_break_produces_no_e1_observations(monkeypatch):
    _quiet_regime(monkeypatch)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda *a, **k: None)

    before = len(fetch_research_observations())
    response = client.post("/api/scan", json={"universe": "Nifty 50", "portfolio_val": 1000000, "risk_pct": 0.01})
    assert response.json()["circuit_breaker_tripped"] is True
    assert len(fetch_research_observations()) == before


def test_normal_scan_still_produces_e1_observations(monkeypatch):
    """The integration point under test is /api/scan -> _persist_scan_history
    -> _record_research_observations -> collect_from_scan -> the real DB
    write (tests/backend/test_prospective_store.py already covers
    collect_from_scan's own field-mapping/idempotency in depth) — not the
    scoring math, which is why apply_advanced_scoring is bypassed here
    rather than hand-built to survive its internal sector/RSI computation.

    Uses a fake, uniquely-named universe/ticker (not real Nifty 50 symbols)
    because E1's observation key is (trading_date=today, symbol,
    scoring_version) — a real symbol could collide with another test file's
    own mocked full-universe scan running the same day against the shared
    test DB, which would (correctly) dedupe as if it were the same signal."""
    _quiet_regime(monkeypatch)
    monkeypatch.setattr(main_mod, "TICKER_GROUPS", {"V4Test Universe": ["ZZV4TEST.NS"]})
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame({"Close": range(250)}))
    monkeypatch.setattr(main_mod, "apply_advanced_scoring", lambda df, config: df)
    monkeypatch.setattr(main_mod, "check_institutional_fortress", lambda ticker, *a, **k: {
        "Symbol": ticker, "Score": 85.0, "Quality_Gate_Pass": True, "Price": 100.0,
        "Technical_Score": 80, "Fundamental_Score": 70, "Sentiment_Score": 60, "Context_Score": 75,
        "Market_Regime": "Range", "Sector": "Energy",
    })

    before = len(fetch_research_observations())
    response = client.post("/api/scan", json={"universe": "V4Test Universe", "portfolio_val": 1000000, "risk_pct": 0.01})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1  # a successful scan returns a bare results array
    after = fetch_research_observations()
    assert len(after) == before + 1
    assert after[-1]["symbol"] == "ZZV4TEST.NS"
