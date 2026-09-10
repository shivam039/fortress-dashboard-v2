"""Tests for stock_scanner.logic.prefetch_metadata() and the fix to
_ensure_metadata_loaded()'s previously-silent failure handling.

Context: fundamental (market cap, debt-to-equity), sentiment (news), and
context (earnings calendar) scores — 50% of the conviction score's combined
weight — have no INDstocks/IndMoney equivalent and always come from
yfinance. What changed here is (a) a DB-backed prefetch so repeat/fresh
scans skip redundant live yfinance calls for tickers already cached, mirroring
a pattern that already existed in the legacy Streamlit UI but was never
ported to this FastAPI-facing module, and (b) making a yfinance metadata
fetch failure visible in the logs instead of silently caching a blank
forever with no trace.

FORTRESS-P2: prefetch_metadata()'s contract changed again — it now also
live-fetches whatever the DB cache read didn't cover, using a bounded
thread pool, instead of leaving that entirely to the per-ticker lazy
`_ensure_metadata_loaded()` fallback inside the scoring loop. See
test_prefetch_metadata_concurrency.py for the concurrency-specific
coverage (bounded pool size, per-ticker result mapping, partial failure
isolation).
"""

import logging

from stock_scanner import logic


def _reset_caches():
    with logic._META_LOCK:
        logic._INFO_CACHE.clear()
        logic._NEWS_CACHE.clear()
        logic._CAL_CACHE.clear()
        logic._EARN_CACHE.clear()


def test_prefetch_metadata_populates_caches_from_db(monkeypatch):
    _reset_caches()

    fake_rows = {
        "PREFETCHA.NS": {
            "info_json": {"marketCap": 999},
            "news_json": [{"title": "headline"}],
            "cal_json": None,
            "earn_json": None,
        }
    }
    monkeypatch.setattr("utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: fake_rows)
    # PREFETCHB.NS is a DB-cache miss, so FORTRESS-P2's concurrent live-fetch
    # tier kicks in for it — mock the live fetch so this test never touches
    # the network, and stub the batch persist so it's a no-op here.
    monkeypatch.setattr(
        logic,
        "_fetch_metadata_live",
        lambda sym: {"info": {"marketCap": 555}, "news": [], "cal_df": None, "earn_df": None},
    )
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", lambda records: None)

    logic.prefetch_metadata(["PREFETCHA.NS", "PREFETCHB.NS"])

    assert logic._INFO_CACHE.get("PREFETCHA.NS") == {"marketCap": 999}
    assert logic._NEWS_CACHE.get("PREFETCHA.NS") == [{"title": "headline"}]
    # Not returned by the fake DB read, so it's a cache miss — FORTRESS-P2:
    # prefetch_metadata() now live-fetches misses itself (bounded
    # concurrency) rather than leaving them for the per-ticker scoring loop.
    assert logic._INFO_CACHE.get("PREFETCHB.NS") == {"marketCap": 555}
    _reset_caches()


def test_prefetch_metadata_returns_stats_dict(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(
        "utils.db.bulk_fetch_metadata",
        lambda syms, max_age_hours=12: {
            "PREFETCHSTATS1.NS": {"info_json": {}, "news_json": [], "cal_json": None, "earn_json": None}
        },
    )
    monkeypatch.setattr(
        logic,
        "_fetch_metadata_live",
        lambda sym: {"info": {}, "news": [], "cal_df": None, "earn_df": None},
    )
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", lambda records: None)

    stats = logic.prefetch_metadata(["PREFETCHSTATS1.NS", "PREFETCHSTATS2.NS"])

    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 1
    assert stats["external_fetches"] == 1
    assert stats["fetch_successes"] == 1
    assert stats["fetch_failures"] == 0
    assert stats["total_duration_s"] >= 0
    _reset_caches()


def test_prefetch_metadata_prevents_live_yfinance_call_for_cached_symbols(monkeypatch):
    _reset_caches()

    monkeypatch.setattr(
        "utils.db.bulk_fetch_metadata",
        lambda syms, max_age_hours=12: {
            "PREFETCHC.NS": {
                "info_json": {"marketCap": 42},
                "news_json": [],
                "cal_json": None,
                "earn_json": None,
            }
        },
    )
    logic.prefetch_metadata(["PREFETCHC.NS"])

    def fail_if_called(*args, **kwargs):
        raise AssertionError("yfinance should not be hit for a symbol prefetch already covered")

    monkeypatch.setattr(logic.yf, "Ticker", fail_if_called)

    # Should return immediately from the in-memory cache without ever
    # constructing a yf.Ticker.
    logic._ensure_metadata_loaded("PREFETCHC.NS")
    assert logic._get_ticker_info("PREFETCHC.NS") == {"marketCap": 42}
    _reset_caches()


def test_prefetch_metadata_empty_symbols_is_a_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: calls.append(syms) or {}
    )
    logic.prefetch_metadata([])
    assert calls == []


def test_prefetch_metadata_swallows_db_errors(monkeypatch):
    _reset_caches()

    def raising(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("utils.db.bulk_fetch_metadata", raising)
    # Must not raise — a DB hiccup here shouldn't fail the whole scan.
    logic.prefetch_metadata(["PREFETCHD.NS"])
    _reset_caches()


def test_ensure_metadata_loaded_logs_on_yfinance_failure(monkeypatch, caplog):
    _reset_caches()

    class _RaisingTicker:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("rate limited")

    monkeypatch.setattr(logic.yf, "Ticker", _RaisingTicker)
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="fortress.scanner"):
        logic._ensure_metadata_loaded("FAILMETA.NS")

    assert any(
        "yfinance metadata fetch failed" in rec.message and "FAILMETA.NS" in rec.message
        for rec in caplog.records
    )
    # Still degrades to empty (unchanged behavior) — just no longer silent.
    assert logic._get_ticker_info("FAILMETA.NS") == {}
    _reset_caches()


def test_ensure_metadata_loaded_success_path_unaffected(monkeypatch):
    _reset_caches()

    class _FakeTicker:
        def __init__(self, symbol):
            self.info = {"marketCap": 777}
            self.news = [{"title": "ok"}]
            self.calendar = None
            self.earnings_dates = None

    monkeypatch.setattr(logic.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache", lambda *a, **k: None)

    logic._ensure_metadata_loaded("OKMETA.NS")

    assert logic._get_ticker_info("OKMETA.NS") == {"marketCap": 777}
    assert logic._get_ticker_news("OKMETA.NS") == [{"title": "ok"}]
    _reset_caches()
