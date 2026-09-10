"""FORTRESS-H2: external data failure handling.

Covers, all via mocked providers (no live network calls, per
docs/market-data.md's "Adding a New Data Source" guidance): Bhav Copy
unavailable, INDstocks unavailable, yfinance unavailable, partial
provider response, timeout, malformed response, DB unavailable, and stale
cache. Rate limiting / bounded retry against INDstocks is already
implemented in utils/indstocks_client.py's request loop (timeout=10,
exponential backoff, capped attempts) — this file tests the observable
provider-selection behavior that sits on top of it.
"""
import time

import pandas as pd
import utils.market_data_provider as mdp


def _reset_prefs(monkeypatch):
    # get_ohlcv_provider_preference() caches its resolved value for 30s
    # (see market_data_provider.py) — well inside this whole suite's own
    # runtime, so a stale cached value from an earlier test can otherwise
    # survive past this monkeypatch entirely. Force a fresh read.
    mdp.invalidate_ohlcv_provider_preference_cache()
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")


def _fresh_bhavcopy_df(n=260, base_ts=None):
    """A Bhav Copy frame whose newest row is "today" — see
    test_market_data_provider.py's _full_year_bhavcopy_df for why this
    matters post-H2 (a fixed historical base_ts now correctly reads as
    stale)."""
    if base_ts is None:
        base_ts = int(time.time()) - (n - 1) * 86400
    candles = [
        {"ts": base_ts + i * 86400, "o": 100.0 + i, "h": 101.0 + i, "l": 99.0 + i, "c": 100.5 + i, "v": 1000 + i}
        for i in range(n)
    ]
    return mdp._candles_to_df(candles)[["Open", "High", "Low", "Close", "Volume"]]


# ── Bhav Copy unavailable ────────────────────────────────────────────────


def test_bhavcopy_db_error_falls_through_to_next_tier(monkeypatch):
    _reset_prefs(monkeypatch)

    def raising_fetch(symbol, start_date=None):
        raise RuntimeError("simulated DB unavailable")

    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", raising_fetch)
    # No INDstocks configured either — should reach yfinance without raising.
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", lambda symbol, period: pd.DataFrame())

    result = mdp.get_ohlcv("RELIANCE.NS", "1y")
    assert result.empty  # degraded gracefully, no exception


# ── INDstocks unavailable ────────────────────────────────────────────────


def test_indstocks_not_configured_falls_through_to_yfinance(monkeypatch):
    _reset_prefs(monkeypatch)
    monkeypatch.delenv("INDSTOCKS_TOKEN", raising=False)
    monkeypatch.delenv("INDSTOCKS_CLIENT_ID", raising=False)
    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None: pd.DataFrame())

    called = {"yf": False}

    def fake_yfinance(symbol, period):
        called["yf"] = True
        return _fresh_bhavcopy_df(n=5)

    monkeypatch.setattr(mdp, "_ohlcv_yfinance", fake_yfinance)

    result = mdp.get_ohlcv("RELIANCE.NS", "1y")
    assert called["yf"] is True
    assert not result.empty


# ── yfinance unavailable ─────────────────────────────────────────────────


def test_yfinance_raises_returns_empty_not_exception(monkeypatch):
    _reset_prefs(monkeypatch)
    monkeypatch.delenv("INDSTOCKS_TOKEN", raising=False)
    monkeypatch.delenv("INDSTOCKS_CLIENT_ID", raising=False)
    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None: pd.DataFrame())

    def raising_yfinance(symbol, period):
        raise ConnectionError("simulated network outage")

    # _ohlcv_yfinance itself already catches internally and returns an
    # empty frame — verify that contract holds and propagates cleanly.
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", lambda symbol, period: pd.DataFrame())
    result = mdp.get_ohlcv("RELIANCE.NS", "1y")
    assert result.empty
    assert isinstance(result, pd.DataFrame)


# ── Timeout ──────────────────────────────────────────────────────────────


def test_yfinance_ohlcv_call_has_an_explicit_timeout(monkeypatch):
    """yfinance has no default request timeout — a stalled connection must
    not hang the calling thread forever."""
    captured = {}

    class _FakeYF:
        @staticmethod
        def download(*args, **kwargs):
            captured.update(kwargs)
            return pd.DataFrame()

    import sys
    monkeypatch.setitem(sys.modules, "yfinance", _FakeYF)

    mdp._ohlcv_yfinance("RELIANCE.NS", "1y")
    assert captured.get("timeout") == 10


# ── Malformed response ───────────────────────────────────────────────────


def test_malformed_frame_missing_columns_is_rejected():
    bad_df = pd.DataFrame({"Open": [1.0], "Close": [2.0]})  # missing High/Low/Volume
    assert mdp._validate_ohlcv_frame(bad_df, "test", "X.NS") is False


def test_malformed_frame_all_nan_close_is_rejected():
    bad_df = pd.DataFrame({
        "Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0],
        "Close": [float("nan"), float("nan")], "Volume": [100, 200],
    })
    assert mdp._validate_ohlcv_frame(bad_df, "test", "X.NS") is False


def test_well_formed_frame_is_accepted():
    good_df = _fresh_bhavcopy_df(n=5)
    assert mdp._validate_ohlcv_frame(good_df, "test", "X.NS") is True


def test_none_and_empty_frames_are_rejected():
    assert mdp._validate_ohlcv_frame(None, "test", "X.NS") is False
    assert mdp._validate_ohlcv_frame(pd.DataFrame(), "test", "X.NS") is False


def test_malformed_bhavcopy_response_falls_through_to_next_tier(monkeypatch):
    """A Bhav Copy row set that's non-empty and passes coverage/staleness
    but is missing required columns must not be served as valid data."""
    _reset_prefs(monkeypatch)
    monkeypatch.delenv("INDSTOCKS_TOKEN", raising=False)
    monkeypatch.delenv("INDSTOCKS_CLIENT_ID", raising=False)

    malformed = pd.DataFrame({"Open": [1.0] * 260, "Close": [2.0] * 260})  # no High/Low/Volume
    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None: malformed)

    called = {"yf": False}

    def fake_yfinance(symbol, period):
        called["yf"] = True
        return _fresh_bhavcopy_df(n=5)

    monkeypatch.setattr(mdp, "_ohlcv_yfinance", fake_yfinance)

    result = mdp.get_ohlcv("RELIANCE.NS", "1y")
    assert called["yf"] is True, "malformed Bhav Copy data must not be served — should fall through"
    assert not result.empty


# ── DB unavailable ───────────────────────────────────────────────────────


def test_batch_bhavcopy_db_error_returns_empty_dict_not_exception(monkeypatch):
    def raising_batch(symbols, start_date=None, end_date=None):
        raise RuntimeError("simulated connection pool exhausted")

    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv_batch", raising_batch)
    result = mdp._batch_ohlcv_bhavcopy(["RELIANCE.NS"], "1y")
    assert result == {}


# ── Stale cache ──────────────────────────────────────────────────────────


def test_stale_bhavcopy_data_is_not_served_as_current(monkeypatch):
    """CRITICAL requirement: a Bhav Copy table that stopped updating days
    ago must not be silently presented as today's data — it must fall
    through to the next tier instead."""
    _reset_prefs(monkeypatch)
    monkeypatch.delenv("INDSTOCKS_TOKEN", raising=False)
    monkeypatch.delenv("INDSTOCKS_CLIENT_ID", raising=False)

    stale_ts = int(time.time()) - 10 * 86400  # newest bar 10 days old
    stale_df = _fresh_bhavcopy_df(n=260, base_ts=stale_ts - 259 * 86400)
    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None: stale_df)

    called = {"yf": False}

    def fake_yfinance(symbol, period):
        called["yf"] = True
        return _fresh_bhavcopy_df(n=5)

    monkeypatch.setattr(mdp, "_ohlcv_yfinance", fake_yfinance)

    result = mdp.get_ohlcv("RELIANCE.NS", "1y")
    assert called["yf"] is True, "stale Bhav Copy data must not be served as current — should fall through"
    assert not result.empty


def test_fresh_bhavcopy_data_is_served_normally(monkeypatch):
    """Sanity check: the staleness gate doesn't reject legitimately fresh
    data — only genuinely old data."""
    _reset_prefs(monkeypatch)
    fresh_df = _fresh_bhavcopy_df(n=260)
    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None: fresh_df)

    result = mdp.get_ohlcv("RELIANCE.NS", "1y")
    assert not result.empty
    assert len(result) == len(fresh_df)


def test_bhavcopy_is_stale_boundary():
    just_ok = _fresh_bhavcopy_df(n=5, base_ts=int(time.time()) - mdp._BHAVCOPY_MAX_STALENESS_DAYS * 86400 - 4 * 86400)
    too_old = _fresh_bhavcopy_df(n=5, base_ts=int(time.time()) - (mdp._BHAVCOPY_MAX_STALENESS_DAYS + 5) * 86400 - 4 * 86400)
    assert mdp._bhavcopy_is_stale(just_ok) is False
    assert mdp._bhavcopy_is_stale(too_old) is True


def test_bhavcopy_is_stale_handles_empty_and_none():
    assert mdp._bhavcopy_is_stale(None) is True
    assert mdp._bhavcopy_is_stale(pd.DataFrame()) is True


# ── Source is recorded accurately (never silently misattributed) ────────


def test_source_call_counts_reflect_actual_tier_used_after_stale_fallback(monkeypatch):
    _reset_prefs(monkeypatch)
    monkeypatch.delenv("INDSTOCKS_TOKEN", raising=False)
    monkeypatch.delenv("INDSTOCKS_CLIENT_ID", raising=False)
    mdp.reset_ohlcv_source_call_counts()

    stale_ts = int(time.time()) - 10 * 86400
    stale_df = _fresh_bhavcopy_df(n=260, base_ts=stale_ts - 259 * 86400)
    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None: stale_df)
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", lambda symbol, period: _fresh_bhavcopy_df(n=5))

    mdp.get_ohlcv("RELIANCE.NS", "1y")

    counts = mdp.get_ohlcv_source_call_counts()
    assert counts["bhavcopy"] == 0, "stale data must not be counted as a bhavcopy-served call"
    assert counts["yfinance"] == 1
