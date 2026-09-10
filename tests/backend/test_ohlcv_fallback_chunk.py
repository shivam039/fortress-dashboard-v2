"""FORTRESS-P2: bounded-concurrency coverage for
stock_scanner.logic.fetch_ohlcv_fallback_chunk() — the per-chunk helper
`/api/scan` uses only when the batch OHLCV fetch returns nothing at all
(engine/main.py's fallback path). No real market-data calls — `fetch_fn` is
always a test double here.
"""

import threading
import time

import pandas as pd
from stock_scanner import logic


def test_fetch_ohlcv_fallback_chunk_bounds_concurrency():
    in_flight = {"current": 0, "peak": 0}
    lock = threading.Lock()

    def fake_fetch(ticker):
        with lock:
            in_flight["current"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        time.sleep(0.02)
        with lock:
            in_flight["current"] -= 1
        return pd.DataFrame({"Close": [1.0]})

    tickers = [f"CHUNK{i}.NS" for i in range(10)]
    result = logic.fetch_ohlcv_fallback_chunk(tickers, max_workers=3, fetch_fn=fake_fetch)

    assert len(result) == 10
    assert in_flight["peak"] <= 3
    assert in_flight["peak"] > 1


def test_fetch_ohlcv_fallback_chunk_maps_results_to_correct_ticker():
    def fake_fetch(ticker):
        # Distinct, ticker-derived payload so a mix-up would be detectable.
        return pd.DataFrame({"Close": [hash(ticker) % 100]})

    tickers = ["MAPX.NS", "MAPY.NS", "MAPZ.NS"]
    result = logic.fetch_ohlcv_fallback_chunk(tickers, max_workers=3, fetch_fn=fake_fetch)

    for t in tickers:
        df, exc = result[t]
        assert exc is None
        assert df["Close"].iloc[0] == hash(t) % 100


def test_fetch_ohlcv_fallback_chunk_isolates_single_ticker_failure():
    def fake_fetch(ticker):
        if ticker == "BADFETCH.NS":
            raise RuntimeError("provider timeout")
        return pd.DataFrame({"Close": [1.0]})

    tickers = ["GOODFETCH1.NS", "BADFETCH.NS", "GOODFETCH2.NS"]
    result = logic.fetch_ohlcv_fallback_chunk(tickers, max_workers=3, fetch_fn=fake_fetch)

    df_good1, exc_good1 = result["GOODFETCH1.NS"]
    assert exc_good1 is None and not df_good1.empty

    df_bad, exc_bad = result["BADFETCH.NS"]
    assert df_bad is None
    assert isinstance(exc_bad, RuntimeError)

    df_good2, exc_good2 = result["GOODFETCH2.NS"]
    assert exc_good2 is None and not df_good2.empty


def test_fetch_ohlcv_fallback_chunk_empty_input_returns_empty_dict():
    assert logic.fetch_ohlcv_fallback_chunk([], fetch_fn=lambda t: pd.DataFrame()) == {}


def test_fetch_ohlcv_fallback_chunk_defaults_to_get_stock_data(monkeypatch):
    """Without an explicit fetch_fn, the chunk helper falls back to the
    module's own get_stock_data() — same call the old fully-serial fallback
    made — so it stays usable by callers other than main.py."""
    calls = []

    def fake_get_stock_data(ticker, period="1y", interval="1d", group_by="column"):
        calls.append(ticker)
        return pd.DataFrame({"Close": [1.0]})

    monkeypatch.setattr(logic, "get_stock_data", fake_get_stock_data)

    result = logic.fetch_ohlcv_fallback_chunk(["DEFAULTFETCH.NS"], max_workers=1)

    assert "DEFAULTFETCH.NS" in calls
    df, exc = result["DEFAULTFETCH.NS"]
    assert exc is None and not df.empty
