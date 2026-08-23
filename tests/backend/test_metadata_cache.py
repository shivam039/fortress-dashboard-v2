"""Tests for the ticker_metadata DB cache in engine/utils/db.py.

`bulk_fetch_metadata()` / `upsert_ticker_metadata_cache()` previously only
worked on Neon (SQLite always hit `if not _can_use_neon(): return`/`return
{}` and no-op'd) — meaning local dev (FORTRESS_DB_BACKEND=sqlite, the
documented default for local dev) never actually cached or reused ticker
metadata (fundamentals/news/calendar/earnings) at all, regardless of how
often the same ticker was scanned. These tests exercise the SQLite path
directly with FORTRESS_DB_BACKEND=sqlite (set by tests/conftest.py) against
the same fortress_history.db file the rest of the backend test suite already
uses, following existing test conventions in this repo (e.g.
test_watchlist_api.py) — using distinctive fake ticker symbols to avoid
colliding with real data.
"""

from utils.db import bulk_fetch_metadata, upsert_ticker_metadata_cache


def test_upsert_then_bulk_fetch_round_trip():
    symbol = "ZZTESTMETA1.NS"
    payload = {
        "info_json": {"marketCap": 123456789, "debtToEquity": 0.42},
        "news_json": [{"title": "Some headline", "summary": "..."}],
        "cal_json": {},
        "earn_json": {},
    }

    upsert_ticker_metadata_cache(symbol, payload)
    result = bulk_fetch_metadata([symbol], max_age_hours=12)

    assert symbol in result
    assert result[symbol]["info_json"]["marketCap"] == 123456789
    assert result[symbol]["info_json"]["debtToEquity"] == 0.42
    assert result[symbol]["news_json"] == [{"title": "Some headline", "summary": "..."}]


def test_upsert_overwrites_existing_row():
    symbol = "ZZTESTMETA2.NS"
    upsert_ticker_metadata_cache(symbol, {"info_json": {"marketCap": 1}, "news_json": []})
    upsert_ticker_metadata_cache(symbol, {"info_json": {"marketCap": 2}, "news_json": []})

    result = bulk_fetch_metadata([symbol], max_age_hours=12)
    assert result[symbol]["info_json"]["marketCap"] == 2


def test_bulk_fetch_only_returns_requested_symbols():
    upsert_ticker_metadata_cache("ZZTESTMETA3.NS", {"info_json": {"marketCap": 3}})
    upsert_ticker_metadata_cache("ZZTESTMETA4.NS", {"info_json": {"marketCap": 4}})

    result = bulk_fetch_metadata(["ZZTESTMETA3.NS"], max_age_hours=12)

    assert "ZZTESTMETA3.NS" in result
    assert "ZZTESTMETA4.NS" not in result


def test_bulk_fetch_excludes_stale_rows(monkeypatch):
    """A row older than max_age_hours must not be returned — simulate this by
    asking for a negative max_age_hours window (i.e. "must have been updated
    in the future"), which no just-written row satisfies."""
    symbol = "ZZTESTMETA5.NS"
    upsert_ticker_metadata_cache(symbol, {"info_json": {"marketCap": 5}})

    fresh = bulk_fetch_metadata([symbol], max_age_hours=12)
    assert symbol in fresh

    stale = bulk_fetch_metadata([symbol], max_age_hours=-1)
    assert symbol not in stale


def test_bulk_fetch_empty_symbol_list_returns_empty_dict():
    assert bulk_fetch_metadata([], max_age_hours=12) == {}


def test_bulk_fetch_unknown_symbol_returns_empty_dict():
    assert bulk_fetch_metadata(["ZZTESTMETA_NEVER_WRITTEN.NS"], max_age_hours=12) == {}
