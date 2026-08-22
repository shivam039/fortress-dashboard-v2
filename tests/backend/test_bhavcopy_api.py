"""Tests for the Bhav Copy / data-provider-toggle HTTP endpoints
(engine/routers/bhavcopy.py): GET/POST /api/settings/data-provider,
POST /api/bhavcopy/refresh, GET /api/bhavcopy/status.

Uses the same TestClient(app) pattern as test_api.py. Monkeypatch targets
use the BARE module paths (bhavcopy.jobs, utils.db, utils.market_data_provider)
because engine/routers/bhavcopy.py's own handlers import those bare and
deferred (inside each route function) — see tests/conftest.py and
test_bhavcopy.py's module docstring for why the bare/`engine.`-prefixed
distinction matters in this repo.
"""

import pytest
from fastapi.testclient import TestClient

from engine.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_ohlcv_preference_cache():
    import utils.market_data_provider as mdp

    mdp.invalidate_ohlcv_provider_preference_cache()
    yield
    mdp.invalidate_ohlcv_provider_preference_cache()


@pytest.fixture(autouse=True)
def _reset_backfill_in_progress_flag():
    import routers.bhavcopy as bhavcopy_router

    bhavcopy_router._backfill_state["in_progress"] = False
    bhavcopy_router._backfill_state["started_at"] = None
    yield
    bhavcopy_router._backfill_state["in_progress"] = False
    bhavcopy_router._backfill_state["started_at"] = None


@pytest.fixture(autouse=True)
def _reset_ohlcv_source_call_counts():
    import utils.market_data_provider as mdp

    mdp.reset_ohlcv_source_call_counts()
    yield
    mdp.reset_ohlcv_source_call_counts()


def test_get_data_provider_defaults_to_bhavcopy(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: default)
    response = client.get("/api/settings/data-provider")
    assert response.status_code == 200
    assert response.json() == {"provider": "bhavcopy"}


def test_set_data_provider_persists_and_is_reflected_immediately(monkeypatch):
    written = {}
    monkeypatch.setattr(
        "utils.db.set_setting", lambda key, value: written.update({key: value})
    )
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: written.get(key, default))

    response = client.post("/api/settings/data-provider", json={"provider": "indstocks"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "indstocks"}
    assert written["ohlcv_provider_preference"] == "indstocks"

    # No stale cache — the very next GET reflects the change.
    follow_up = client.get("/api/settings/data-provider")
    assert follow_up.json() == {"provider": "indstocks"}


def test_set_data_provider_rejects_unknown_value():
    response = client.post("/api/settings/data-provider", json={"provider": "carrier-pigeon"})
    assert response.status_code == 400
    assert "carrier-pigeon" in response.json()["detail"]


def test_bhavcopy_refresh_returns_202_and_schedules_background_job(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "bhavcopy.jobs.run_bhavcopy_refresh_job",
        lambda force=False: calls.append(force) or {"status": "done"},
    )

    response = client.post("/api/bhavcopy/refresh", json={"force": True})
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    # TestClient runs BackgroundTasks synchronously after the response body
    # is built, so by the time we get here the job has already run.
    assert calls == [True]


def test_bhavcopy_status_reports_never_attempted_when_nothing_logged(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda trade_date: None)
    response = client.get("/api/bhavcopy/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "never_attempted"
    assert "trade_date" in body


def test_bhavcopy_status_reports_recorded_status(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda trade_date: "done")
    response = client.get("/api/bhavcopy/status")
    assert response.json()["status"] == "done"


def test_market_data_status_includes_ohlcv_source(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")
    response = client.get("/api/market-data-status")
    assert response.status_code == 200
    body = response.json()
    assert body["ohlcv_source"] == "bhavcopy"
    assert body["ohlcv_source_label"] == "NSE Bhav Copy"


# ── /api/bhavcopy/status coverage summary ───────────────────────────────


def test_bhavcopy_status_includes_coverage_summary(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda trade_date: "done")
    monkeypatch.setattr(
        "utils.db.get_bhavcopy_coverage_summary",
        lambda: {
            "trading_days_covered": 42,
            "symbol_count": 1800,
            "earliest_date": "2026-01-01",
            "latest_date": "2026-06-01",
        },
    )
    response = client.get("/api/bhavcopy/status")
    body = response.json()
    assert body["trading_days_covered"] == 42
    assert body["symbol_count"] == 1800
    assert body["earliest_date"] == "2026-01-01"
    assert body["latest_date"] == "2026-06-01"
    assert body["backfill_in_progress"] is False


# ── /api/bhavcopy/status ohlcv_calls_by_source + /api/bhavcopy/reset-stats ──
# The "real proof" fields — distinct from the coverage summary above and
# from ohlcv_source/ohlcv_source_label (which just reflect the preference
# setting, see test_market_data_status_includes_ohlcv_source). These reflect
# what actually served OHLCV calls since process start or the last
# POST /api/bhavcopy/reset-stats.


def test_bhavcopy_status_includes_zeroed_call_counts_by_default(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda trade_date: None)
    response = client.get("/api/bhavcopy/status")
    assert response.json()["ohlcv_calls_by_source"] == {
        "bhavcopy": 0,
        "indstocks": 0,
        "yfinance": 0,
    }


def test_bhavcopy_status_reflects_calls_served_since_last_reset(monkeypatch):
    import utils.market_data_provider as mdp

    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda trade_date: None)
    mdp._record_ohlcv_source("bhavcopy", count=7)
    mdp._record_ohlcv_source("indstocks", count=2)

    response = client.get("/api/bhavcopy/status")
    counts = response.json()["ohlcv_calls_by_source"]
    assert counts == {"bhavcopy": 7, "indstocks": 2, "yfinance": 0}


def test_reset_stats_zeroes_the_counters(monkeypatch):
    import utils.market_data_provider as mdp

    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda trade_date: None)
    mdp._record_ohlcv_source("bhavcopy", count=5)
    assert client.get("/api/bhavcopy/status").json()["ohlcv_calls_by_source"]["bhavcopy"] == 5

    response = client.post("/api/bhavcopy/reset-stats")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    follow_up = client.get("/api/bhavcopy/status")
    assert follow_up.json()["ohlcv_calls_by_source"] == {
        "bhavcopy": 0,
        "indstocks": 0,
        "yfinance": 0,
    }


# ── /api/bhavcopy/backfill ──────────────────────────────────────────────


def test_backfill_returns_202_and_schedules_background_job(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "bhavcopy.jobs.backfill_bhavcopy",
        lambda days=300: calls.append(days)
        or {"done": ["2026-01-01"], "skipped_no_data": [], "errors": {}},
    )

    response = client.post("/api/bhavcopy/backfill", json={"days": 30})
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    # TestClient runs BackgroundTasks synchronously after the response body
    # is built, so by the time we get here the (mocked) backfill has run.
    assert calls == [30]


def test_backfill_defaults_to_300_days_when_unspecified(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "bhavcopy.jobs.backfill_bhavcopy",
        lambda days=300: calls.append(days) or {"done": [], "skipped_no_data": [], "errors": {}},
    )
    response = client.post("/api/bhavcopy/backfill", json={})
    assert response.status_code == 202
    assert calls == [300]


def test_backfill_rejects_out_of_range_days():
    response = client.post("/api/bhavcopy/backfill", json={"days": 0})
    assert response.status_code == 400

    response = client.post("/api/bhavcopy/backfill", json={"days": 99999})
    assert response.status_code == 400


def test_backfill_rejects_a_second_concurrent_request(monkeypatch):
    import routers.bhavcopy as bhavcopy_router

    bhavcopy_router._backfill_state["in_progress"] = True

    response = client.post("/api/bhavcopy/backfill", json={"days": 30})
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_backfill_clears_in_progress_flag_even_if_the_job_raises(monkeypatch):
    import routers.bhavcopy as bhavcopy_router

    def _boom(days=300):
        raise RuntimeError("NSE is down")

    monkeypatch.setattr("bhavcopy.jobs.backfill_bhavcopy", _boom)

    response = client.post("/api/bhavcopy/backfill", json={"days": 30})
    assert response.status_code == 202  # the HTTP response was already sent
    # ...but the background task's own exception must not leave the guard stuck.
    assert bhavcopy_router._backfill_state["in_progress"] is False
