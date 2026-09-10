"""FORTRESS-P2: concurrency-specific coverage for prefetch_metadata()'s live
fetch tier (`_prefetch_metadata_concurrently`).

Covers: the thread pool is bounded (never exceeds the configured worker
count), each future's result is mapped back to its own ticker regardless of
completion order, and one ticker's provider failure never affects another
ticker's result or aborts the batch. No real yfinance/network calls —
`_fetch_metadata_live` is monkeypatched throughout.
"""

import threading
import time

from stock_scanner import logic


def _reset_caches():
    with logic._META_LOCK:
        logic._INFO_CACHE.clear()
        logic._NEWS_CACHE.clear()
        logic._CAL_CACHE.clear()
        logic._EARN_CACHE.clear()


def test_concurrency_never_exceeds_configured_worker_count(monkeypatch):
    _reset_caches()
    symbols = [f"CONC{i}.NS" for i in range(12)]
    max_workers = 3

    in_flight = {"current": 0, "peak": 0}
    lock = threading.Lock()

    def fake_fetch(symbol):
        with lock:
            in_flight["current"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        time.sleep(0.02)  # hold the "slot" long enough for overlap to show
        with lock:
            in_flight["current"] -= 1
        return {"info": {"marketCap": 1}, "news": [], "cal_df": None, "earn_df": None}

    monkeypatch.setattr(logic, "_fetch_metadata_live", fake_fetch)

    successes, failures = logic._prefetch_metadata_concurrently(symbols, max_workers)

    assert len(successes) == 12
    assert failures == []
    assert in_flight["peak"] <= max_workers
    assert in_flight["peak"] > 1  # actually ran concurrently, not serially
    _reset_caches()


def test_prefetch_metadata_bounds_workers_via_env(monkeypatch):
    _reset_caches()
    monkeypatch.setenv("FORTRESS_METADATA_FETCH_WORKERS", "2")
    monkeypatch.setattr("utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: {})
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", lambda records: None)

    in_flight = {"current": 0, "peak": 0}
    lock = threading.Lock()

    def fake_fetch(symbol):
        with lock:
            in_flight["current"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        time.sleep(0.02)
        with lock:
            in_flight["current"] -= 1
        return {"info": {}, "news": [], "cal_df": None, "earn_df": None}

    monkeypatch.setattr(logic, "_fetch_metadata_live", fake_fetch)

    stats = logic.prefetch_metadata([f"ENVCONC{i}.NS" for i in range(8)])

    assert stats["concurrency"] == 2
    assert in_flight["peak"] <= 2
    _reset_caches()


def test_results_mapped_to_correct_ticker_regardless_of_completion_order(monkeypatch):
    _reset_caches()
    # Symbols finish in reverse order (first submitted sleeps longest), to
    # make sure results are attributed by future->symbol mapping, not by
    # completion/submission order.
    symbols = ["ORDER_A.NS", "ORDER_B.NS", "ORDER_C.NS"]
    delays = {"ORDER_A.NS": 0.06, "ORDER_B.NS": 0.03, "ORDER_C.NS": 0.0}

    def fake_fetch(symbol):
        time.sleep(delays[symbol])
        return {
            "info": {"marketCap": hash(symbol) % 1000},
            "news": [{"title": symbol}],
            "cal_df": None,
            "earn_df": None,
        }

    monkeypatch.setattr(logic, "_fetch_metadata_live", fake_fetch)

    successes, failures = logic._prefetch_metadata_concurrently(symbols, 3)

    assert failures == []
    for sym in symbols:
        assert successes[sym]["news_json"] == [{"title": sym}]
        assert logic._INFO_CACHE[sym]["marketCap"] == hash(sym) % 1000
    _reset_caches()


def test_one_ticker_failure_does_not_affect_others_or_abort_batch(monkeypatch):
    _reset_caches()
    symbols = ["OKMETA1.NS", "FAILMETA1.NS", "OKMETA2.NS"]

    def fake_fetch(symbol):
        if symbol == "FAILMETA1.NS":
            raise RuntimeError("simulated provider failure")
        return {"info": {"marketCap": 42}, "news": [], "cal_df": None, "earn_df": None}

    monkeypatch.setattr(logic, "_fetch_metadata_live", fake_fetch)

    successes, failures = logic._prefetch_metadata_concurrently(symbols, 3)

    assert failures == ["FAILMETA1.NS"]
    assert set(successes.keys()) == {"OKMETA1.NS", "OKMETA2.NS"}
    # Failed ticker still gets the same blank-default fallback
    # _ensure_metadata_loaded has always used on failure — never left
    # entirely out of the cache (which would recreate a live retry later).
    assert logic._INFO_CACHE["FAILMETA1.NS"] == {}
    assert logic._NEWS_CACHE["FAILMETA1.NS"] == []
    assert logic._INFO_CACHE["OKMETA1.NS"] == {"marketCap": 42}
    assert logic._INFO_CACHE["OKMETA2.NS"] == {"marketCap": 42}
    _reset_caches()


def test_prefetch_metadata_partial_failure_does_not_raise(monkeypatch):
    """End-to-end through prefetch_metadata(): a provider failure for one
    ticker in a cold-cache batch must not raise or abort the rest."""
    _reset_caches()
    monkeypatch.setattr("utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: {})
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", lambda records: None)

    def fake_fetch(symbol):
        if symbol == "PARTIALFAIL.NS":
            raise RuntimeError("rate limited")
        return {"info": {"marketCap": 7}, "news": [], "cal_df": None, "earn_df": None}

    monkeypatch.setattr(logic, "_fetch_metadata_live", fake_fetch)

    stats = logic.prefetch_metadata(["PARTIALOK.NS", "PARTIALFAIL.NS"])

    assert stats["fetch_successes"] == 1
    assert stats["fetch_failures"] == 1
    assert logic._get_ticker_info("PARTIALOK.NS") == {"marketCap": 7}
    assert logic._get_ticker_info("PARTIALFAIL.NS") == {}  # degraded default, not an exception
    _reset_caches()


def test_batch_persistence_called_once_with_only_successful_results(monkeypatch):
    _reset_caches()
    monkeypatch.setattr("utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: {})

    persisted = {}

    def fake_batch_upsert(records):
        persisted.update(records)

    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", fake_batch_upsert)

    def fake_fetch(symbol):
        if symbol == "PERSISTFAIL.NS":
            raise RuntimeError("boom")
        return {"info": {"marketCap": 1}, "news": [], "cal_df": None, "earn_df": None}

    monkeypatch.setattr(logic, "_fetch_metadata_live", fake_fetch)

    logic.prefetch_metadata(["PERSISTOK.NS", "PERSISTFAIL.NS"])

    assert set(persisted.keys()) == {"PERSISTOK.NS"}
    _reset_caches()
