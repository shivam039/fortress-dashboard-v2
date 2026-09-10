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

from utils.db import (
    bulk_fetch_metadata,
    upsert_ticker_metadata_cache,
    upsert_ticker_metadata_cache_batch,
)


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


# ── FORTRESS-P2: batched write-back (upsert_ticker_metadata_cache_batch) ────


def test_batch_upsert_persists_multiple_records_in_one_call():
    records = {
        "ZZBATCH1.NS": {"info_json": {"marketCap": 111}, "news_json": [{"title": "a"}]},
        "ZZBATCH2.NS": {"info_json": {"marketCap": 222}, "news_json": []},
        "ZZBATCH3.NS": {"info_json": {"marketCap": 333}, "news_json": []},
    }

    upsert_ticker_metadata_cache_batch(records)

    result = bulk_fetch_metadata(list(records.keys()), max_age_hours=12)
    assert set(result.keys()) == set(records.keys())
    assert result["ZZBATCH1.NS"]["info_json"]["marketCap"] == 111
    assert result["ZZBATCH1.NS"]["news_json"] == [{"title": "a"}]
    assert result["ZZBATCH2.NS"]["info_json"]["marketCap"] == 222
    assert result["ZZBATCH3.NS"]["info_json"]["marketCap"] == 333


def test_batch_upsert_updates_existing_rows_and_refreshes_timestamp():
    symbol = "ZZBATCHUPDATE.NS"
    upsert_ticker_metadata_cache(symbol, {"info_json": {"marketCap": 1}})

    upsert_ticker_metadata_cache_batch({symbol: {"info_json": {"marketCap": 2}}})

    result = bulk_fetch_metadata([symbol], max_age_hours=12)
    assert result[symbol]["info_json"]["marketCap"] == 2
    # Cache semantics preserved: a fresh row is still fresh (not expired by
    # the batch path using a different timestamp mechanism).
    assert symbol in bulk_fetch_metadata([symbol], max_age_hours=12)
    assert symbol not in bulk_fetch_metadata([symbol], max_age_hours=-1)


def test_batch_upsert_empty_records_is_a_noop():
    # Must not raise on an empty dict (e.g. every fetch in a batch failed).
    upsert_ticker_metadata_cache_batch({})


def test_batch_upsert_matches_single_item_upsert_semantics():
    """Same end-state whether one ticker is persisted via the single-item
    API or the batch API — the batch path must preserve exactly the same
    upsert semantics (ON CONFLICT update, same JSON shape read back)."""
    payload = {"info_json": {"marketCap": 999, "debtToEquity": 1.5}, "news_json": [{"title": "x"}]}

    upsert_ticker_metadata_cache("ZZSINGLE.NS", payload)
    upsert_ticker_metadata_cache_batch({"ZZBATCHEQUIV.NS": payload})

    single = bulk_fetch_metadata(["ZZSINGLE.NS"], max_age_hours=12)["ZZSINGLE.NS"]
    batched = bulk_fetch_metadata(["ZZBATCHEQUIV.NS"], max_age_hours=12)["ZZBATCHEQUIV.NS"]
    assert single["info_json"] == batched["info_json"]
    assert single["news_json"] == batched["news_json"]
