"""Tests for the mf_lab NAV/OHLCV DB caches in engine/utils/db.py and the
bulk pre-seed step in engine/mf_lab/logic.py.

`fetch_mf_nav_cache`/`upsert_mf_nav_cache`, `fetch_ohlcv_cache`/
`upsert_ohlcv_cache`, and `_bulk_preseed_nav_cache` previously only worked on
Neon (SQLite always hit `if not _can_use_neon(): return None`/`{}` and
no-op'd). Combined with `run_full_mf_scan()` discovering essentially the
whole direct-growth mutual fund universe when called with no `limit` (as the
frontend does), this meant local dev (FORTRESS_DB_BACKEND=sqlite) re-downloaded
NAV history from mfapi.in live for every single fund on every single scan,
with zero caching benefit even between back-to-back scans — the main reason
MF scans were slow. These tests exercise the SQLite path directly against the
same fortress_history.db file the rest of the backend suite uses, following
existing conventions (e.g. test_metadata_cache.py) — using distinctive fake
scheme codes/symbols to avoid colliding with real data.
"""

import pandas as pd

from engine.mf_lab.logic import _bulk_preseed_nav_cache
from engine.utils.db import (
    fetch_mf_nav_cache,
    fetch_ohlcv_cache,
    upsert_mf_nav_cache,
    upsert_ohlcv_cache,
)


def _fake_nav_df(n=5, start_val=100.0):
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({"nav": [start_val + i for i in range(n)]}, index=idx)


def test_mf_nav_cache_round_trip():
    code = "ZZTESTNAV1"
    df = _fake_nav_df()

    upsert_mf_nav_cache(code, df)
    result = fetch_mf_nav_cache(code, max_age_hours=24)

    assert result is not None
    assert not result.empty
    assert list(result["nav"]) == list(df["nav"])


def test_mf_nav_cache_excludes_stale_rows():
    code = "ZZTESTNAV2"
    upsert_mf_nav_cache(code, _fake_nav_df())

    fresh = fetch_mf_nav_cache(code, max_age_hours=24)
    assert fresh is not None

    stale = fetch_mf_nav_cache(code, max_age_hours=-1)
    assert stale is None


def test_mf_nav_cache_unknown_code_returns_none():
    assert fetch_mf_nav_cache("ZZTESTNAV_NEVER_WRITTEN", max_age_hours=24) is None


def test_mf_nav_cache_upsert_overwrites():
    code = "ZZTESTNAV3"
    upsert_mf_nav_cache(code, _fake_nav_df(start_val=1.0))
    upsert_mf_nav_cache(code, _fake_nav_df(start_val=999.0))

    result = fetch_mf_nav_cache(code, max_age_hours=24)
    assert result["nav"].iloc[0] == 999.0


def test_ohlcv_cache_round_trip():
    symbol = "ZZTESTOHLCV1"
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {"Open": [1.0, 2.0, 3.0], "Close": [1.5, 2.5, 3.5]}, index=idx
    )

    upsert_ohlcv_cache(symbol, "5y", df)
    result = fetch_ohlcv_cache(symbol, period="5y", max_age_hours=24)

    assert result is not None
    assert list(result["Close"]) == [1.5, 2.5, 3.5]


def test_ohlcv_cache_excludes_stale_rows():
    symbol = "ZZTESTOHLCV2"
    idx = pd.date_range("2026-01-01", periods=2, freq="D")
    upsert_ohlcv_cache(symbol, "5y", pd.DataFrame({"Close": [1.0, 2.0]}, index=idx))

    assert fetch_ohlcv_cache(symbol, period="5y", max_age_hours=24) is not None
    assert fetch_ohlcv_cache(symbol, period="5y", max_age_hours=-1) is None


def test_ohlcv_cache_scoped_by_period():
    symbol = "ZZTESTOHLCV3"
    idx = pd.date_range("2026-01-01", periods=2, freq="D")
    upsert_ohlcv_cache(symbol, "1y", pd.DataFrame({"Close": [1.0, 2.0]}, index=idx))

    assert fetch_ohlcv_cache(symbol, period="1y", max_age_hours=24) is not None
    assert fetch_ohlcv_cache(symbol, period="5y", max_age_hours=24) is None


def test_bulk_preseed_nav_cache_reads_back_upserted_funds():
    codes = ["ZZTESTNAV_BULK1", "ZZTESTNAV_BULK2", "ZZTESTNAV_BULK3"]
    upsert_mf_nav_cache(codes[0], _fake_nav_df(start_val=10.0))
    upsert_mf_nav_cache(codes[1], _fake_nav_df(start_val=20.0))
    # codes[2] deliberately never written — must be absent, not None-valued.

    seeded = _bulk_preseed_nav_cache(codes)

    assert set(seeded.keys()) == {codes[0], codes[1]}
    assert seeded[codes[0]]["nav"].iloc[0] == 10.0
    assert seeded[codes[1]]["nav"].iloc[0] == 20.0


def test_bulk_preseed_nav_cache_empty_codes_is_a_noop():
    assert _bulk_preseed_nav_cache([]) == {}
