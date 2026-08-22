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
