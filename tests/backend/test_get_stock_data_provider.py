"""Tests for the provider selection inside `stock_scanner.logic.get_stock_data`.

`get_stock_data` is the function every bulk scan (`/api/scan`, `/api/sector-pulse`)
funnels through. These tests pin down the contract added alongside
`market_data_provider.get_batch_ohlcv()`:

  - Full INDstocks coverage for a batch request -> INDstocks data is used,
    yfinance is never called.
  - Partial INDstocks coverage -> only the missing symbols are gap-filled from
    yfinance and merged with the INDstocks data (previously this discarded
    the whole INDstocks batch and re-fetched every symbol from yfinance,
    which meant paying for both providers on every scan with any partial
    miss — in practice, every scan, since the instruments cache has no
    index coverage).
  - Gap-fill itself failing -> falls through to a full yfinance batch fetch
    as a last resort.
  - INDstocks unavailable/erroring -> unchanged yfinance behaviour.

`get_stock_data` is `@lru_cache`d, so every test uses distinct fake ticker
symbols and clears the cache in a fixture to avoid cross-test pollution.
"""

import pandas as pd
import pytest
import utils.market_data_provider as mdp_bare

from engine.stock_scanner import logic


@pytest.fixture(autouse=True)
def _clear_get_stock_data_cache():
    logic.get_stock_data.cache_clear()
    yield
    logic.get_stock_data.cache_clear()


def _fake_ohlcv_df(n=3):
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "Open": [100.0] * n,
            "High": [101.0] * n,
            "Low": [99.0] * n,
            "Close": [100.5] * n,
            "Volume": [1000.0] * n,
        },
        index=idx,
    )


def test_batch_uses_indstocks_when_fully_covered(monkeypatch):
    symbols = ("FAKEA1.NS", "FAKEA2.NS")

    def fake_get_batch_ohlcv(syms, period="1y"):
        assert set(syms) == set(symbols)
        return {s: _fake_ohlcv_df() for s in syms}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("yfinance should not be called when INDstocks covers the batch")

    monkeypatch.setattr(mdp_bare, "get_batch_ohlcv", fake_get_batch_ohlcv)
    monkeypatch.setattr(logic.yf, "download", fail_if_called)

    result = logic.get_stock_data(symbols, period="1y", interval="1d", group_by="ticker")

    assert not result.empty
    assert isinstance(result.columns, pd.MultiIndex)
    assert set(result.columns.get_level_values(0)) == set(symbols)
    for sym in symbols:
        assert list(result[sym].columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_batch_gap_fills_only_missing_symbols_on_partial_coverage(monkeypatch):
    """The common case: INDstocks covers most of the batch (e.g. 49/50 real
    equities) but misses one or two symbols. Only those missing symbols
    should go to yfinance — not the whole batch — so a single INDstocks miss
    doesn't force paying for both providers on every scan."""
    symbols = ("FAKEB1.NS", "FAKEB2.NS", "FAKEB3.NS")

    def fake_get_batch_ohlcv(syms, period="1y"):
        # Only the first symbol came back from INDstocks.
        return {syms[0]: _fake_ohlcv_df()}

    yf_calls = []

    def fake_yf_download(symbol, **kwargs):
        yf_calls.append(list(symbol))
        cols = pd.MultiIndex.from_product([list(symbol), ["Open", "High", "Low", "Close", "Volume"]])
        idx = pd.date_range("2026-01-01", periods=3, freq="D")
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(mdp_bare, "get_batch_ohlcv", fake_get_batch_ohlcv)
    monkeypatch.setattr(logic.yf, "download", fake_yf_download)

    result = logic.get_stock_data(symbols, period="1y", interval="1d", group_by="ticker")

    assert len(yf_calls) == 1, "yfinance should be called exactly once, for the gap-fill"
    assert set(yf_calls[0]) == {"FAKEB2.NS", "FAKEB3.NS"}, (
        "yfinance must only be asked for the symbols INDstocks missed, not the whole batch"
    )
    assert not result.empty
    assert set(result.columns.get_level_values(0)) == set(symbols)
    # The INDstocks-covered symbol's data should be the INDstocks frame (all 100.5 closes),
    # not overwritten by the yfinance gap-fill data (all 1.0 closes).
    assert (result["FAKEB1.NS"]["Close"] == 100.5).all()


def test_batch_gap_fill_single_missing_symbol(monkeypatch):
    """When only one symbol is missing, yfinance drops the MultiIndex level
    for a single-symbol list — this must still be handled correctly."""
    symbols = ("FAKEE1.NS", "FAKEE2.NS")

    def fake_get_batch_ohlcv(syms, period="1y"):
        return {syms[0]: _fake_ohlcv_df()}

    def fake_yf_download(symbol, **kwargs):
        assert list(symbol) == ["FAKEE2.NS"]
        idx = pd.date_range("2026-01-01", periods=3, freq="D")
        return pd.DataFrame(
            {"Open": [1.0] * 3, "High": [1.0] * 3, "Low": [1.0] * 3, "Close": [1.0] * 3, "Volume": [1.0] * 3},
            index=idx,
        )

    monkeypatch.setattr(mdp_bare, "get_batch_ohlcv", fake_get_batch_ohlcv)
    monkeypatch.setattr(logic.yf, "download", fake_yf_download)

    result = logic.get_stock_data(symbols, period="1y", interval="1d", group_by="ticker")

    assert not result.empty
    assert set(result.columns.get_level_values(0)) == set(symbols)


def test_batch_falls_back_to_full_yfinance_when_gap_fill_fails(monkeypatch):
    """If the yfinance gap-fill call itself blows up, fall through to the
    original full-batch yfinance fetch as a last resort rather than
    returning nothing."""
    symbols = ("FAKEF1.NS", "FAKEF2.NS")

    def fake_get_batch_ohlcv(syms, period="1y"):
        return {syms[0]: _fake_ohlcv_df()}

    calls = []

    def flaky_yf_download(symbol, **kwargs):
        syms = list(symbol) if not isinstance(symbol, str) else [symbol]
        calls.append(syms)
        if len(calls) == 1:
            raise RuntimeError("yfinance gap-fill boom")
        cols = pd.MultiIndex.from_product([syms, ["Open", "High", "Low", "Close", "Volume"]])
        idx = pd.date_range("2026-01-01", periods=2, freq="D")
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(mdp_bare, "get_batch_ohlcv", fake_get_batch_ohlcv)
    monkeypatch.setattr(logic.yf, "download", flaky_yf_download)
    monkeypatch.setattr(logic.time, "sleep", lambda *_: None)

    result = logic.get_stock_data(symbols, period="1y", interval="1d", group_by="ticker")

    assert len(calls) >= 2, "must retry via the full yfinance batch path after the gap-fill fails"
    assert not result.empty


def test_batch_falls_back_to_yfinance_when_indstocks_unavailable(monkeypatch):
    symbols = ("FAKEC1.NS", "FAKEC2.NS")

    def fake_get_batch_ohlcv(syms, period="1y"):
        return {}

    yf_calls = []

    def fake_yf_download(symbol, **kwargs):
        yf_calls.append(symbol)
        cols = pd.MultiIndex.from_product([list(symbol), ["Open", "High", "Low", "Close", "Volume"]])
        idx = pd.date_range("2026-01-01", periods=2, freq="D")
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(mdp_bare, "get_batch_ohlcv", fake_get_batch_ohlcv)
    monkeypatch.setattr(logic.yf, "download", fake_yf_download)

    result = logic.get_stock_data(symbols, period="1y", interval="1d", group_by="ticker")

    assert yf_calls
    assert not result.empty


def test_batch_falls_back_to_yfinance_when_provider_raises(monkeypatch):
    symbols = ("FAKED1.NS", "FAKED2.NS")

    def raising_get_batch_ohlcv(*args, **kwargs):
        raise RuntimeError("boom")

    yf_calls = []

    def fake_yf_download(symbol, **kwargs):
        yf_calls.append(symbol)
        cols = pd.MultiIndex.from_product([list(symbol), ["Open", "High", "Low", "Close", "Volume"]])
        idx = pd.date_range("2026-01-01", periods=2, freq="D")
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(mdp_bare, "get_batch_ohlcv", raising_get_batch_ohlcv)
    monkeypatch.setattr(logic.yf, "download", fake_yf_download)

    result = logic.get_stock_data(symbols, period="1y", interval="1d", group_by="ticker")

    assert yf_calls
    assert not result.empty
