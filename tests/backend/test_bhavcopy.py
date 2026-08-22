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


_SAMPLE_ROWS = [
    {
        "TckrSymb": "RELIANCE",
        "SctySrs": "EQ",
        "OpnPric": 2500.0,
        "HghPric": 2550.0,
        "LwPric": 2490.0,
        "ClsPric": 2530.0,
        "TtlTradgVol": 1000000,
        "TtlTrdgVal": 2500000000.0,
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
        "TtlTrdgVal": 1900000000.0,
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
        "TtlTrdgVal": 1000.0,
        "DlvryQty": 5,
        "DlvryPct": 50.0,
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
    assert reliance["deliv_pct"] == 40.0


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


# ── app_settings (used by the provider-preference toggle in a later phase) ──


def test_get_setting_returns_default_when_unset():
    assert db_mod.get_setting("no_such_setting_key", default="fallback") == "fallback"


def test_set_setting_and_get_setting_roundtrip():
    db_mod.set_setting("ohlcv_provider_preference", "bhavcopy")
    assert db_mod.get_setting("ohlcv_provider_preference") == "bhavcopy"

    db_mod.set_setting("ohlcv_provider_preference", "indstocks")
    assert db_mod.get_setting("ohlcv_provider_preference") == "indstocks"
