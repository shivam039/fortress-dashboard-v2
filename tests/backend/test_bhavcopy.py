"""Tests for engine/bhavcopy/ (fetch/parse) and its DB persistence layer.

No live network calls — NSE fetches are mocked at the requests.Session
boundary. Module imports use the BARE form (`bhavcopy.logic`, `bhavcopy.jobs`,
`utils.db`) rather than `engine.bhavcopy...`/`engine.utils.db`, matching this
repo's established convention (see tests/conftest.py and
test_reit_distributions.py): engine/bhavcopy/jobs.py does its own internal
imports as `from bhavcopy.logic import ...` / `from utils.db import ...`
(bare), which is what actually resolves on Render (Root Directory=engine).
Importing under `engine.bhavcopy...` in a test would create a second,
separate module object that monkeypatch.setattr calls here would silently
miss — see .agent-room/anti-patterns.md for the general form of this bug.
"""

import io
import uuid
import zipfile
from datetime import date

import pandas as pd
import pytest

import bhavcopy.jobs as bhavcopy_jobs
import bhavcopy.logic as bhavcopy_logic
import utils.db as db_mod


def _make_bhavcopy_zip(rows: list[dict]) -> bytes:
    """Build an in-memory zip matching NSE's UDiFF column layout, for tests
    that need a realistic download payload without hitting the network."""
    df = pd.DataFrame(rows)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BhavCopy_NSE_CM_0_0_0_20260101_F_0000.csv", csv_bytes)
    return buf.getvalue()


# Column names here match a REAL downloaded UDiFF CM Bhav Copy file
# (verified via the chartiny/nse-cm-bhavcopy GitHub mirror), not just what
# the code happened to expect — using `TtlTrdgVal` here previously let a
# one-letter mismatch (the real column is `TtlTrfVal`) go undetected,
# because the fixture and the (buggy) `_COLUMN_MAP` agreed with each other
# instead of with NSE. `DlvryQty`/`DlvryPct` are NOT part of the real file
# at all — see the "no delivery columns" test below, which is the one that
# reflects actual production data. They're kept here anyway (harmlessly
# exercising the DlvryQty/DlvryPct branch of `_COLUMN_MAP`) so a future
# format change that *adds* delivery columns back is still covered.
_SAMPLE_ROWS = [
    {
        "TckrSymb": "RELIANCE",
        "SctySrs": "EQ",
        "OpnPric": 2500.0,
        "HghPric": 2550.0,
        "LwPric": 2490.0,
        "ClsPric": 2530.0,
        "TtlTradgVol": 1000000,
        "TtlTrfVal": 2500000000.0,
        "DlvryQty": 400000,
        "DlvryPct": 40.0,
    },
    {
        "TckrSymb": "TCS",
        "SctySrs": "EQ",
        "OpnPric": 3800.0,
        "HghPric": 3850.0,
        "LwPric": 3790.0,
        "ClsPric": 3820.0,
        "TtlTradgVol": 500000,
        "TtlTrfVal": 1900000000.0,
        "DlvryQty": 200000,
        "DlvryPct": 40.0,
    },
    {
        # Non-equity series (e.g. a debt instrument bundled into the same
        # file) — must be filtered out.
        "TckrSymb": "SOMEDEBT",
        "SctySrs": "N1",
        "OpnPric": 100.0,
        "HghPric": 100.0,
        "LwPric": 100.0,
        "ClsPric": 100.0,
        "TtlTradgVol": 10,
        "TtlTrfVal": 1000.0,
        "DlvryQty": 5,
        "DlvryPct": 50.0,
    },
]

# The shape NSE actually publishes at this endpoint: no delivery columns at
# all. A real file also has extra columns this parser ignores (e.g. ISIN,
# SctySrsPrvsClsg-style fields); trimming to just what _COLUMN_MAP cares
# about plus one unrecognised extra column is enough to prove those don't
# break parsing.
_REAL_SHAPE_ROWS = [
    {
        "TckrSymb": "RELIANCE",
        "SctySrs": "EQ",
        "OpnPric": 2500.0,
        "HghPric": 2550.0,
        "LwPric": 2490.0,
        "ClsPric": 2530.0,
        "TtlTradgVol": 1000000,
        "TtlTrfVal": 2500000000.0,
        "ISIN": "INE002A01018",
    },
]


# ── parsing ──────────────────────────────────────────────────────────────


def test_parse_bhavcopy_zip_normalises_columns_and_filters_to_equity_series():
    raw = _make_bhavcopy_zip(_SAMPLE_ROWS)
    df = bhavcopy_logic.parse_bhavcopy_zip(raw)

    assert set(df["symbol"]) == {"RELIANCE.NS", "TCS.NS"}
    assert "SOMEDEBT.NS" not in set(df["symbol"])

    reliance = df[df["symbol"] == "RELIANCE.NS"].iloc[0]
    assert reliance["close"] == 2530.0
    assert reliance["volume"] == 1000000
    assert reliance["turnover"] == 2500000000.0
    assert reliance["deliv_pct"] == 40.0


def test_parse_bhavcopy_zip_handles_real_file_shape_with_no_delivery_columns():
    """Production reality: NSE's UDiFF CM Bhav Copy at this endpoint has no
    DlvryQty/DlvryPct columns at all (confirmed against a real downloaded
    file — see bhavcopy/logic.py module docstring). OHLCV/turnover must
    still parse correctly, and deliv_qty/deliv_pct must come back absent
    (not present-but-null) rather than raising."""
    raw = _make_bhavcopy_zip(_REAL_SHAPE_ROWS)
    df = bhavcopy_logic.parse_bhavcopy_zip(raw)

    reliance = df[df["symbol"] == "RELIANCE.NS"].iloc[0]
    assert reliance["close"] == 2530.0
    assert reliance["volume"] == 1000000
    assert reliance["turnover"] == 2500000000.0
    assert "deliv_qty" not in df.columns
    assert "deliv_pct" not in df.columns


def test_parse_bhavcopy_zip_raises_format_error_on_unrecognised_columns():
    df = pd.DataFrame([{"SomeColumn": 1, "AnotherColumn": 2}])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bad.csv", df.to_csv(index=False).encode("utf-8"))

    with pytest.raises(bhavcopy_logic.BhavCopyFormatError):
        bhavcopy_logic.parse_bhavcopy_zip(buf.getvalue())


def test_download_zip_raises_unavailable_on_404(monkeypatch):
    class _FakeResponse:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("should not be called after a 404 short-circuit")

    class _FakeSession:
        def get(self, url, timeout=None):
            return _FakeResponse()

    with pytest.raises(bhavcopy_logic.BhavCopyUnavailable):
        bhavcopy_logic._download_zip(date(2026, 1, 1), session=_FakeSession())


# ── jobs.run_bhavcopy_refresh_job ───────────────────────────────────────


def test_refresh_job_skips_network_call_when_already_marked_done(monkeypatch):
    monkeypatch.setattr(db_mod, "get_bhavcopy_fetch_status", lambda d: "done")

    def _boom(*a, **k):
        raise AssertionError("fetch_bhavcopy should not be called when already done")

    monkeypatch.setattr(bhavcopy_logic, "fetch_bhavcopy", _boom)

    result = bhavcopy_jobs.run_bhavcopy_refresh_job(trade_date=date(2026, 1, 1))
    assert result["status"] == "skipped"


def test_refresh_job_persists_rows_and_records_done_on_success(monkeypatch):
    sample_df = bhavcopy_logic.parse_bhavcopy_zip(_make_bhavcopy_zip(_SAMPLE_ROWS))

    monkeypatch.setattr(db_mod, "get_bhavcopy_fetch_status", lambda d: None)
    monkeypatch.setattr(bhavcopy_logic, "fetch_bhavcopy", lambda d, session=None: sample_df)

    recorded = {}
    monkeypatch.setattr(
        db_mod,
        "record_bhavcopy_fetch",
        lambda d, status, symbol_count=0, error_detail=None: recorded.update(
            {"trade_date": d, "status": status, "symbol_count": symbol_count}
        ),
    )
    written = {}
    monkeypatch.setattr(
        db_mod,
        "upsert_bhavcopy_rows",
        lambda df, d: written.setdefault("count", len(df)) or len(df),
    )

    result = bhavcopy_jobs.run_bhavcopy_refresh_job(trade_date=date(2026, 1, 1))

    assert result["status"] == "done"
    assert result["symbol_count"] == 2
    assert recorded["status"] == "done"
    assert recorded["symbol_count"] == 2


def test_refresh_job_marks_not_yet_published_without_erroring(monkeypatch):
    monkeypatch.setattr(db_mod, "get_bhavcopy_fetch_status", lambda d: None)

    def _unavailable(d, session=None):
        raise bhavcopy_logic.BhavCopyUnavailable("not published yet")

    monkeypatch.setattr(bhavcopy_logic, "fetch_bhavcopy", _unavailable)

    recorded = {}
    monkeypatch.setattr(
        db_mod,
        "record_bhavcopy_fetch",
        lambda d, status, symbol_count=0, error_detail=None: recorded.update({"status": status}),
    )

    result = bhavcopy_jobs.run_bhavcopy_refresh_job(trade_date=date(2026, 1, 1))
    assert result["status"] == "not_yet_published"
    assert recorded["status"] == "not_yet_published"


def test_refresh_job_force_bypasses_dedup_check(monkeypatch):
    calls = {"status_checks": 0}

    def _status(d):
        calls["status_checks"] += 1
        return "done"

    monkeypatch.setattr(db_mod, "get_bhavcopy_fetch_status", _status)
    sample_df = bhavcopy_logic.parse_bhavcopy_zip(_make_bhavcopy_zip(_SAMPLE_ROWS))
    monkeypatch.setattr(bhavcopy_logic, "fetch_bhavcopy", lambda d, session=None: sample_df)
    monkeypatch.setattr(db_mod, "record_bhavcopy_fetch", lambda *a, **k: None)
    monkeypatch.setattr(db_mod, "upsert_bhavcopy_rows", lambda df, d: len(df))

    result = bhavcopy_jobs.run_bhavcopy_refresh_job(trade_date=date(2026, 1, 1), force=True)
    assert result["status"] == "done"
    assert calls["status_checks"] == 0  # force=True skips the check entirely


# ── DB persistence layer (real SQLite, no mocks) ────────────────────────


def test_upsert_and_fetch_bhavcopy_ohlcv_roundtrip():
    df = pd.DataFrame(
        [
            {"symbol": "TESTSYM.NS", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1000},
            {"symbol": "OTHER.NS", "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.5, "volume": 500},
        ]
    )
    written = db_mod.upsert_bhavcopy_rows(df, "2026-06-01")
    assert written == 2

    result = db_mod.fetch_bhavcopy_ohlcv("TESTSYM.NS")
    assert not result.empty
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert result.iloc[-1]["Close"] == 104.0


def test_upsert_bhavcopy_rows_is_idempotent_per_symbol_and_date():
    df1 = pd.DataFrame([{"symbol": "IDEMP.NS", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100}])
    df2 = pd.DataFrame([{"symbol": "IDEMP.NS", "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.5, "volume": 200}])

    db_mod.upsert_bhavcopy_rows(df1, "2026-06-02")
    db_mod.upsert_bhavcopy_rows(df2, "2026-06-02")  # same symbol+date: should overwrite, not duplicate

    result = db_mod.fetch_bhavcopy_ohlcv("IDEMP.NS", start_date="2026-06-02", end_date="2026-06-02")
    assert len(result) == 1
    assert result.iloc[0]["Close"] == 11.5


def test_fetch_bhavcopy_ohlcv_returns_empty_df_for_unknown_symbol():
    result = db_mod.fetch_bhavcopy_ohlcv("NOSUCHSYMBOL.NS")
    assert result.empty


def test_upsert_bhavcopy_rows_bulk_batch_all_rows_persist_correctly():
    """upsert_bhavcopy_rows batches every row into a single _exec_many() call
    (one connection/transaction for the whole DataFrame) instead of one
    _exec() call per row — added after a real day's ~2400-symbol Bhav Copy
    file was found taking minutes to write via the old per-row loop, each
    row opening its own connection/transaction against Neon. This pins down
    that the batched path still writes every row correctly, not just the
    1-2 row cases the other tests above already cover."""
    prefix = uuid.uuid4().hex[:6]
    n = 25
    df = pd.DataFrame(
        [
            {
                "symbol": f"BULK{prefix}{i}.NS",
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1000 + i,
            }
            for i in range(n)
        ]
    )

    written = db_mod.upsert_bhavcopy_rows(df, "2026-06-03")
    assert written == n

    for i in (0, n // 2, n - 1):
        result = db_mod.fetch_bhavcopy_ohlcv(
            f"BULK{prefix}{i}.NS", start_date="2026-06-03", end_date="2026-06-03"
        )
        assert len(result) == 1
        assert result.iloc[0]["Close"] == 100.5 + i


def test_get_bhavcopy_coverage_summary_reflects_stored_data():
    # Other tests in this file/session also write into bhavcopy_eod, so we
    # can't assert an exact global row count here — instead pin dates far
    # outside any real trading-day range (nothing else in this suite writes
    # 1900 or 2099) so the min/max assertions are deterministic regardless
    # of what else has been written to the shared dev DB.
    unique_symbol = f"COVTEST{uuid.uuid4().hex[:6]}.NS"
    row = pd.DataFrame(
        [{"symbol": unique_symbol, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}]
    )
    db_mod.upsert_bhavcopy_rows(row, "1900-01-01")
    db_mod.upsert_bhavcopy_rows(row, "2099-12-31")

    summary = db_mod.get_bhavcopy_coverage_summary()
    assert summary["trading_days_covered"] >= 2
    assert summary["symbol_count"] >= 1
    assert summary["earliest_date"] == "1900-01-01"
    assert summary["latest_date"] == "2099-12-31"


def test_bhavcopy_fetch_log_dedup_marker():
    # SQLite-backend tests share one on-disk fortress_history.db across the
    # whole pytest session (not a fresh :memory: db per test), so a literal
    # date like "2026-07-01" could collide with a leftover row from a
    # previous run of this same test file. A synthetic, run-unique key sidesteps
    # that instead of depending on run order/isolation.
    marker_date = f"2026-07-01-test-{uuid.uuid4().hex[:8]}"

    assert db_mod.get_bhavcopy_fetch_status(marker_date) is None
    db_mod.record_bhavcopy_fetch(marker_date, status="done", symbol_count=1500)
    assert db_mod.get_bhavcopy_fetch_status(marker_date) == "done"

    # Re-recording (e.g. a forced re-run) overwrites rather than erroring.
    db_mod.record_bhavcopy_fetch(marker_date, status="error", error_detail="boom")
    assert db_mod.get_bhavcopy_fetch_status(marker_date) == "error"


# ── jobs.backfill_bhavcopy ──────────────────────────────────────────────


def test_backfill_bhavcopy_chunk_limit_aborts_early(monkeypatch):
    # Mock time.sleep to avoid waiting 1.5s per iteration in test
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    # Mock the refresh job so it always does a "network fetch"
    # and counts as a fetch towards max_fetches.
    def mock_refresh(*args, **kwargs):
        return {"status": "done", "trade_date": "2026-01-01", "error": None}
    
    monkeypatch.setattr(bhavcopy_jobs, "run_bhavcopy_refresh_job", mock_refresh)

    # Request 300 days but limit to 5 fetches
    result = bhavcopy_jobs.backfill_bhavcopy(days=300, start_from=date(2026, 8, 1), max_fetches=5)
    
    # Verify it stopped exactly after 5 fetches (len(done) == 5 since all return "done")
    assert len(result["done"]) == 5
    assert len(result["skipped_no_data"]) == 0
    assert len(result["errors"]) == 0


def test_backfill_bhavcopy_progress_cb_called(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    
    def mock_refresh(*args, **kwargs):
        return {"status": "skipped", "trade_date": "2026-01-01", "error": None}
    
    monkeypatch.setattr(bhavcopy_jobs, "run_bhavcopy_refresh_job", mock_refresh)

    progress_calls = []
    def on_progress(processed, total):
        progress_calls.append((processed, total))

    # Request 5 days, no fetch limit
    # Because mock_refresh returns "skipped", fetch_count stays 0.
    # We use a Thursday so we have 2 weekdays + 2 weekend days + 1 weekday.
    # Start: 2026-08-06 (Thursday). 5 days -> Thursday, Wednesday, Tuesday, Monday, Sunday.
    # Wait, dates go backwards. So: 06 (Thu), 05 (Wed), 04 (Tue), 03 (Mon), 02 (Sun).
    # All 5 days should trigger the progress callback.
    bhavcopy_jobs.backfill_bhavcopy(days=5, start_from=date(2026, 8, 6), progress_cb=on_progress)

    assert len(progress_calls) == 5
    assert progress_calls[-1] == (5, 5)


def test_backfill_bhavcopy_single_fatal_error_does_not_abort_the_run(monkeypatch):
    """A lone fatal_error day (NSE serving an HTML block page instead of a
    zip for that one date — see run_bhavcopy_refresh_job) must not stop the
    whole backfill: production hit exactly this, where one stubborn date
    got retried as the first live fetch of every chunk forever, permanently
    blocking progress on every older date behind it."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = []

    def mock_refresh(trade_date, force=False, session=None):
        calls.append(trade_date.isoformat())
        if trade_date.isoformat() == "2026-08-05":
            return {"status": "fatal_error", "trade_date": "2026-08-05", "symbol_count": 0, "error": "boom"}
        return {"status": "done", "trade_date": trade_date.isoformat(), "symbol_count": 1, "error": None}

    monkeypatch.setattr(bhavcopy_jobs, "run_bhavcopy_refresh_job", mock_refresh)

    # 2026-08-06 (Thu), 08-05 (Wed, the bad one), 08-04 (Tue), 08-03 (Mon)
    result = bhavcopy_jobs.backfill_bhavcopy(days=4, start_from=date(2026, 8, 6), max_fetches=0)

    assert calls == ["2026-08-06", "2026-08-05", "2026-08-04", "2026-08-03"], (
        "the loop must keep walking past the one bad day instead of stopping there"
    )
    assert result["errors"] == {"2026-08-05": "boom"}
    assert "2026-08-06" in result["done"] and "2026-08-04" in result["done"] and "2026-08-03" in result["done"]


def test_backfill_bhavcopy_aborts_after_consecutive_fatal_errors(monkeypatch):
    """Unlike one bad day, a *streak* of fatal errors in a row is the real
    signal of a sustained block and should still stop the run early rather
    than burning through the whole chunk."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = []

    def mock_refresh(trade_date, force=False, session=None):
        calls.append(trade_date.isoformat())
        return {"status": "fatal_error", "trade_date": trade_date.isoformat(), "symbol_count": 0, "error": "boom"}

    monkeypatch.setattr(bhavcopy_jobs, "run_bhavcopy_refresh_job", mock_refresh)

    result = bhavcopy_jobs.backfill_bhavcopy(days=300, start_from=date(2026, 8, 6), max_fetches=0)

    assert len(calls) == bhavcopy_jobs._MAX_CONSECUTIVE_FATAL_ERRORS
    assert len(result["errors"]) == bhavcopy_jobs._MAX_CONSECUTIVE_FATAL_ERRORS


def test_refresh_job_defers_retry_of_a_recently_fatal_errored_date(monkeypatch):
    """Once a date has fatally failed, retrying it seconds later must NOT
    hit NSE again — this is what previously made the backfill hammer the
    exact same blocked URL on every single chunk. It should only retry
    after the cooldown window passes (or force=True)."""
    from datetime import datetime, timezone

    monkeypatch.setattr(db_mod, "get_bhavcopy_fetch_status", lambda d: "fatal_error")
    monkeypatch.setattr(
        db_mod,
        "get_bhavcopy_fetch_log_entry",
        lambda d: {
            "status": "fatal_error",
            # Real datetime, matching what SQLAlchemy returns for a Neon
            # TIMESTAMPTZ column (SQLite returns a "YYYY-MM-DD HH:MM:SS"
            # string instead — _seconds_since() handles both).
            "fetched_at": datetime.now(timezone.utc),
            "error_detail": "File is not a zip file",
        },
    )

    def _boom(*a, **k):
        raise AssertionError("fetch_bhavcopy should not be called during the cooldown window")

    monkeypatch.setattr(bhavcopy_logic, "fetch_bhavcopy", _boom)

    result = bhavcopy_jobs.run_bhavcopy_refresh_job(trade_date=date(2026, 6, 26))
    assert result["status"] == "skipped_recent_fatal_error"


def test_refresh_job_retries_a_fatal_error_date_once_cooldown_expires(monkeypatch):
    """Symmetric to the deferral test above: once the cooldown window has
    passed, the date should be retried like any other pending day."""
    from datetime import datetime, timedelta, timezone

    old_enough = datetime.now(timezone.utc) - timedelta(
        seconds=bhavcopy_jobs._FATAL_ERROR_RETRY_COOLDOWN_S + 60
    )
    monkeypatch.setattr(db_mod, "get_bhavcopy_fetch_status", lambda d: "fatal_error")
    monkeypatch.setattr(
        db_mod,
        "get_bhavcopy_fetch_log_entry",
        lambda d: {"status": "fatal_error", "fetched_at": old_enough, "error_detail": "boom"},
    )

    sample_df = bhavcopy_logic.parse_bhavcopy_zip(_make_bhavcopy_zip(_SAMPLE_ROWS))
    monkeypatch.setattr(bhavcopy_logic, "fetch_bhavcopy", lambda d, session=None: sample_df)
    monkeypatch.setattr(db_mod, "record_bhavcopy_fetch", lambda *a, **k: None)
    monkeypatch.setattr(db_mod, "upsert_bhavcopy_rows", lambda df, d: len(df))

    result = bhavcopy_jobs.run_bhavcopy_refresh_job(trade_date=date(2026, 6, 26))
    assert result["status"] == "done"


# ── app_settings (used by the provider-preference toggle in a later phase) ──


def test_get_setting_returns_default_when_unset():
    assert db_mod.get_setting("no_such_setting_key", default="fallback") == "fallback"


def test_set_setting_and_get_setting_roundtrip():
    db_mod.set_setting("ohlcv_provider_preference", "bhavcopy")
    assert db_mod.get_setting("ohlcv_provider_preference") == "bhavcopy"

    db_mod.set_setting("ohlcv_provider_preference", "indstocks")
    assert db_mod.get_setting("ohlcv_provider_preference") == "indstocks"
