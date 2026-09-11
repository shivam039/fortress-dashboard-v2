"""Tests for the scan_jobs DB-backed job-state table (utils/db.py),
FORTRESS-P3. Exercised directly against SQLite (FORTRESS_DB_BACKEND=sqlite,
set by tests/conftest.py) — no HTTP layer, no background tasks.
"""

from utils.db import (
    _sqlite_connection,
    complete_scan_job,
    create_scan_job,
    fail_scan_job,
    get_scan_job,
    heartbeat_scan_job,
    mark_stale_scan_jobs_failed,
    update_scan_job_progress,
)


def test_create_scan_job_inserts_queued_row():
    job_id = "job-create-1"
    create_scan_job(job_id, "Nifty 50", {"universe": "Nifty 50", "portfolio_val": 1000000})

    job = get_scan_job(job_id)
    assert job is not None
    assert job["status"] == "queued"
    assert job["universe"] == "Nifty 50"
    assert job["request_json"]["portfolio_val"] == 1000000
    assert job["results_json"] is None
    assert job["error"] is None


def test_update_scan_job_progress_sets_only_given_fields():
    job_id = "job-progress-1"
    create_scan_job(job_id, "Nifty 50", {})

    update_scan_job_progress(job_id, status="running", stage="metadata", current=0, total=50, message="Prefetching")
    job = get_scan_job(job_id)
    assert job["status"] == "running"
    assert job["stage"] == "metadata"
    assert job["progress_current"] == 0
    assert job["progress_total"] == 50
    assert job["message"] == "Prefetching"

    # Partial update — only stage/current/message change, status/total untouched.
    update_scan_job_progress(job_id, stage="indicators", current=25, message="Scoring 25/50")
    job = get_scan_job(job_id)
    assert job["status"] == "running"  # unchanged
    assert job["stage"] == "indicators"
    assert job["progress_current"] == 25
    assert job["progress_total"] == 50  # unchanged
    assert job["message"] == "Scoring 25/50"


def test_complete_scan_job_stores_results_and_marks_completed():
    job_id = "job-complete-1"
    create_scan_job(job_id, "Nifty 50", {})
    update_scan_job_progress(job_id, status="running", stage="indicators", current=50, total=50)

    results = [{"Symbol": "RELIANCE.NS", "Score": 72.5}, {"Symbol": "TCS.NS", "Score": 65.0}]
    complete_scan_job(job_id, results)

    job = get_scan_job(job_id)
    assert job["status"] == "completed"
    assert job["stage"] == "completed"
    assert job["results_json"] == results


def test_complete_scan_job_preserves_dict_shaped_results():
    """execute_scan()'s "aborted early"/"no results" responses are a dict,
    not a bare list — the job store must round-trip either shape exactly."""
    job_id = "job-complete-dict-1"
    create_scan_job(job_id, "Nifty 50", {})

    dict_results = {
        "results": [],
        "summary": "No tickers met criteria or market data was unavailable.",
        "scanned": 50,
        "failed": 0,
        "circuit_breaker_tripped": False,
    }
    complete_scan_job(job_id, dict_results)

    job = get_scan_job(job_id)
    assert job["results_json"] == dict_results


def test_fail_scan_job_stores_visible_error():
    job_id = "job-fail-1"
    create_scan_job(job_id, "Nifty 50", {})
    update_scan_job_progress(job_id, status="running", stage="indicators")

    fail_scan_job(job_id, "simulated provider outage")

    job = get_scan_job(job_id)
    assert job["status"] == "failed"
    assert job["stage"] == "failed"
    assert job["error"] == "simulated provider outage"
    assert job["results_json"] is None


def test_mark_stale_scan_jobs_failed_recovers_orphaned_jobs(monkeypatch):
    monkeypatch.setenv("FORTRESS_SCAN_JOB_STALE_SECONDS", "1")
    job_id = "job-stale-1"
    create_scan_job(job_id, "Nifty 50", {})

    with _sqlite_connection() as conn:
        conn.execute(
            "UPDATE scan_jobs SET status='running', updated_at=datetime('now', '-2 minutes') WHERE job_id = :job_id",
            {"job_id": job_id},
        )
        conn.commit()

    count = mark_stale_scan_jobs_failed(1)
    assert count == 1

    job = get_scan_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "Scan interrupted or worker unavailable. Please retry."


def test_get_scan_job_marks_stale_running_jobs_failed_on_read(monkeypatch):
    monkeypatch.setenv("FORTRESS_SCAN_JOB_STALE_SECONDS", "1")
    job_id = "job-stale-read-1"
    create_scan_job(job_id, "Nifty 50", {})

    with _sqlite_connection() as conn:
        conn.execute(
            "UPDATE scan_jobs SET status='running', updated_at=datetime('now', '-2 minutes') WHERE job_id = :job_id",
            {"job_id": job_id},
        )
        conn.commit()

    job = get_scan_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == "Scan interrupted or worker unavailable. Please retry."


def test_get_scan_job_returns_none_for_unknown_job_id():
    assert get_scan_job("does-not-exist-job-id") is None


def test_update_scan_job_progress_unknown_job_id_does_not_raise():
    # No row exists for this id — must be a no-op, not an exception (a
    # progress-write race/typo must never crash the scan it's tracking).
    update_scan_job_progress("no-such-job", status="running")


def test_progress_updates_refresh_updated_at_timestamp():
    job_id = "job-timestamp-1"
    create_scan_job(job_id, "Nifty 50", {})
    job1 = get_scan_job(job_id)

    update_scan_job_progress(job_id, stage="metadata", current=1, total=10)
    job2 = get_scan_job(job_id)

    assert job2["updated_at"] is not None
    assert job1["created_at"] is not None


def test_heartbeat_refreshes_running_job_timestamp():
    job_id = "job-heartbeat-1"
    create_scan_job(job_id, "Nifty 50", {})
    update_scan_job_progress(job_id, status="running", stage="market_data")

    with _sqlite_connection() as conn:
        conn.execute(
            "UPDATE scan_jobs SET updated_at=datetime('now', '-2 minutes') "
            "WHERE job_id = :job_id",
            {"job_id": job_id},
        )
        conn.commit()

    before = get_scan_job(job_id)["updated_at"]
    assert heartbeat_scan_job(job_id) == 1
    after = get_scan_job(job_id)["updated_at"]
    assert after >= before


def test_heartbeat_cannot_mutate_terminal_job():
    job_id = "job-heartbeat-terminal-1"
    create_scan_job(job_id, "Nifty 50", {})
    complete_scan_job(job_id, [])

    assert heartbeat_scan_job(job_id) == 0
    job = get_scan_job(job_id)
    assert job["status"] == "completed"
    assert job["stage"] == "completed"
