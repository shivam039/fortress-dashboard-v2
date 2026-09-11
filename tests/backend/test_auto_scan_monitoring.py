"""FORTRESS-O1: operational monitoring for the E3 pipeline. Detection
only — no scans, no evidence writes, no retry loops. See
docs/research/PRODUCTION_OPERATIONS.md.
"""
import uuid
from datetime import datetime, timezone

import research.auto_scan as auto_scan
from research.auto_scan import check_pipeline_health, check_production_config
from utils.db import create_auto_scan_run, update_auto_scan_run

# Each test gets its own trading_date so fetch_latest_auto_scan_run(trading_date=...)
# never picks up a different test's row from this shared SQLite test DB — the
# same rerun-safety technique used in test_auto_scan.py.
_TAG = uuid.uuid4().hex[:8]
_DATE = f"2025-05-01-{_TAG}"


def _make_run(run_id, status, trading_date=_DATE, **fields):
    create_auto_scan_run(run_id, trading_date, ["Nifty 50"], datetime.now(timezone.utc).isoformat())
    update_auto_scan_run(run_id, status=status, completed_at=datetime.now(timezone.utc).isoformat(), **fields)
    return trading_date


def test_complete_run_is_healthy(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda d: "done")
    date = _make_run("o1-complete-1", "COMPLETE", trading_date=f"{_DATE}-a", observations_inserted=42)
    result = check_pipeline_health(trading_date=date)
    assert result["level"] == "OK"


def test_degraded_run_is_a_warning_not_complete(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda d: "done")
    date = _make_run(
        "o1-degraded-1", "DEGRADED", trading_date=f"{_DATE}-b",
        unresolved_universes=["Ghost Universe"], reason="unresolved universes: Ghost Universe",
    )
    result = check_pipeline_health(trading_date=date)
    assert result["level"] == "WARNING"
    assert result["reason"] == "RUN_DEGRADED"
    assert result["unresolved_universes"] == ["Ghost Universe"]


def test_failed_run_is_an_alert():
    date = _make_run(
        "o1-failed-1", "FAILED", trading_date=f"{_DATE}-c",
        reason="bhavcopy_not_ready:error", circuit_breaker_tripped=False,
    )
    result = check_pipeline_health(trading_date=date)
    assert result["level"] == "ALERT"
    assert result["reason"] == "RUN_FAILED"
    assert result["failure_reason"] == "bhavcopy_not_ready:error"


def test_missing_run_before_grace_window_is_ok(monkeypatch):
    class _Early(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 5, 2, 10, 0, tzinfo=tz)  # 10:00 UTC, before grace

    monkeypatch.setattr(auto_scan, "datetime", _Early)
    result = check_pipeline_health(trading_date="2025-05-02")
    assert result["level"] == "OK"


def test_missing_run_after_grace_window_is_an_alert(monkeypatch):
    class _Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 5, 3, 20, 0, tzinfo=tz)  # 20:00 UTC, past grace

    monkeypatch.setattr(auto_scan, "datetime", _Late)
    result = check_pipeline_health(trading_date="2025-05-03")
    assert result["level"] == "ALERT"
    assert result["reason"] == "EXPECTED_RUN_MISSING"


def test_stale_evidence_after_complete_run_is_an_alert(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda d: "done")
    date = _make_run("o1-stale-1", "COMPLETE", trading_date=f"{_DATE}-d", observations_inserted=0)
    result = check_pipeline_health(trading_date=date)
    assert result["level"] == "ALERT"
    assert result["reason"] == "STALE_EVIDENCE"
    assert "no_observations_inserted_despite_complete_run" in result["issues"]


def test_stale_bhavcopy_after_complete_run_is_an_alert(monkeypatch):
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda d: "not_yet_published")
    date = _make_run("o1-stale-2", "COMPLETE", trading_date=f"{_DATE}-e", observations_inserted=10)
    result = check_pipeline_health(trading_date=date)
    assert result["level"] == "ALERT"
    assert any("bhavcopy_not_current" in i for i in result["issues"])


def test_repeated_invocation_is_safe_and_deterministic(monkeypatch):
    """A watchdog re-run (e.g. after its own retry) must never duplicate
    scans/evidence — this function is read-only, so calling it twice must
    return the same result with no side effects."""
    monkeypatch.setattr("utils.db.get_bhavcopy_fetch_status", lambda d: "done")
    date = _make_run("o1-dup-1", "COMPLETE", trading_date=f"{_DATE}-f", observations_inserted=5)
    first = check_pipeline_health(trading_date=date)
    second = check_pipeline_health(trading_date=date)
    assert first == second


def test_production_config_reports_booleans_only_never_secret_values(monkeypatch):
    monkeypatch.setenv("FORTRESS_AUTO_SCAN_UNIVERSES", "Nifty 50,Nifty Next 50,Nifty Midcap 150,Nifty Smallcap 250")
    monkeypatch.setenv("FORTRESS_API_KEY", "super-secret-key-value")
    monkeypatch.setenv("FORTRESS_JWT_SECRET", "super-secret-jwt-value")
    result = check_production_config()
    assert result["universes_configured_correctly"] is True
    assert result["fortress_api_key_set"] is True
    assert result["fortress_jwt_secret_set"] is True
    serialized = str(result)
    assert "super-secret-key-value" not in serialized
    assert "super-secret-jwt-value" not in serialized


def test_production_config_flags_missing_universes_without_leaking_actual_value(monkeypatch):
    monkeypatch.setenv("FORTRESS_AUTO_SCAN_UNIVERSES", "Nifty 50")
    result = check_production_config()
    assert result["universes_configured_correctly"] is False
    assert result["expected_universes_env"] == "Nifty 50,Nifty Next 50,Nifty Midcap 150,Nifty Smallcap 250"
