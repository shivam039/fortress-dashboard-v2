"""Tests for the monthly MF scan persistence in engine/utils/db.py
(`fetch_mf_cached_results`/`upsert_mf_scan_results`) and for how
`/api/mf-analysis` uses it.

Context: the mf_scan_results table and its read/write functions already
existed and were clearly designed for a "run the full MF scan once a month,
serve cached results in between" workflow (`fetch_mf_cached_results` takes a
`max_age_days` freshness window) — but `fetch_mf_cached_results` returned an
empty DataFrame immediately on SQLite (`if not _can_use_neon(): return
pd.DataFrame()`), and `/api/mf-analysis` never called it at all, always
running a full discover-and-score pass instead. These tests cover: the
SQLite round trip for the cache itself, and that the API route actually
prefers a fresh cache over re-scanning.
"""

import pandas as pd
from fastapi.testclient import TestClient

import engine.main as main_mod
from engine.main import app
from engine.utils.db import fetch_mf_cached_results, upsert_mf_scan_results

client = TestClient(app)


def _fake_scan_df():
    return pd.DataFrame(
        [
            {
                "Scheme Code": "ZZTESTSCAN1",
                "Scheme": "Test Fund One Direct Growth",
                "Category": "Equity",
                "Sub Category": "Small Cap",
                "Conviction Score": 72.5,
            },
            {
                "Scheme Code": "ZZTESTSCAN2",
                "Scheme": "Test Fund Two Direct Growth",
                "Category": "Debt",
                "Sub Category": "Liquid",
                "Conviction Score": 55.0,
            },
        ]
    )


def test_upsert_then_fetch_mf_scan_results_round_trip():
    upsert_mf_scan_results(_fake_scan_df())

    result = fetch_mf_cached_results(max_age_days=31)

    codes = set(result["Scheme Code"]) if not result.empty else set()
    assert {"ZZTESTSCAN1", "ZZTESTSCAN2"}.issubset(codes)


def test_fetch_mf_cached_results_excludes_stale_scans():
    upsert_mf_scan_results(_fake_scan_df())

    fresh = fetch_mf_cached_results(max_age_days=31)
    assert not fresh.empty

    # A just-written row can never satisfy "updated in the future".
    stale = fetch_mf_cached_results(max_age_days=-1)
    stale_codes = set(stale["Scheme Code"]) if not stale.empty else set()
    assert "ZZTESTSCAN1" not in stale_codes


def test_fetch_mf_cached_results_stamps_last_updated():
    upsert_mf_scan_results(_fake_scan_df())

    result = fetch_mf_cached_results(max_age_days=31)
    row = result[result["Scheme Code"] == "ZZTESTSCAN1"].iloc[0]
    assert row.get("last_updated")


def test_upsert_mf_scan_results_empty_df_is_a_noop():
    # Must not raise.
    upsert_mf_scan_results(pd.DataFrame())


def test_mf_analysis_serves_from_cache_when_fresh(monkeypatch):
    """The whole point of the monthly cache: a fresh scan on file must
    short-circuit the expensive discover-and-score pass entirely."""
    cached_df = _fake_scan_df()

    monkeypatch.setattr(main_mod, "fetch_mf_cached_results", lambda max_age_days=31: cached_df)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_full_mf_scan must not run when a fresh cache exists")

    monkeypatch.setattr(main_mod, "run_full_mf_scan", fail_if_called)

    response = client.get("/api/mf-analysis")
    assert response.status_code == 200
    codes = {r.get("Scheme Code") for r in response.json()}
    assert {"ZZTESTSCAN1", "ZZTESTSCAN2"}.issubset(codes)


def test_mf_analysis_runs_fresh_scan_when_cache_is_empty(monkeypatch):
    monkeypatch.setattr(main_mod, "fetch_mf_cached_results", lambda max_age_days=31: pd.DataFrame())

    calls = []

    def fake_scan(limit=None):
        calls.append(limit)
        return _fake_scan_df()

    monkeypatch.setattr(main_mod, "run_full_mf_scan", fake_scan)

    response = client.get("/api/mf-analysis")
    assert response.status_code == 200
    assert calls, "run_full_mf_scan must run when there is no fresh cache"


def test_mf_analysis_force_refresh_bypasses_cache(monkeypatch):
    cached_df = _fake_scan_df()
    monkeypatch.setattr(main_mod, "fetch_mf_cached_results", lambda max_age_days=31: cached_df)

    calls = []

    def fake_scan(limit=None):
        calls.append(limit)
        return _fake_scan_df()

    monkeypatch.setattr(main_mod, "run_full_mf_scan", fake_scan)

    response = client.get("/api/mf-analysis", params={"force_refresh": "true"})
    assert response.status_code == 200
    assert calls, "force_refresh=true must bypass a fresh cache and run a new scan"
