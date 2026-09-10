"""FORTRESS-P2 scoring-equivalence evidence.

P2 changed *how* ticker metadata gets into stock_scanner.logic's in-memory
caches (a bounded-concurrency prefetch instead of a per-ticker lazy fetch)
but must not change *what* check_institutional_fortress() /
apply_advanced_scoring() compute from that cache. These tests populate the
same in-memory caches for the same deterministic OHLCV fixture via two
different paths — a direct write (standing in for a warm DB-cache prefetch,
or the pre-P2 lazy-fetch end state) vs. the new concurrent
prefetch_metadata() path — and assert byte-identical scoring output.
"""


import pandas as pd
from stock_scanner import logic


def _reset_caches():
    with logic._META_LOCK:
        logic._INFO_CACHE.clear()
        logic._NEWS_CACHE.clear()
        logic._CAL_CACHE.clear()
        logic._EARN_CACHE.clear()


class _TA:
    """Deterministic indicator stub, same shape as
    test_stock_scanner_scoring.py's — isolates this test from pandas_ta's
    own internals, which P2 does not touch."""

    @staticmethod
    def ema(series, length):
        value = {200: 90.0, 50: 95.0, 20: 98.0, 30: 92.0}.get(length, 90.0)
        return pd.Series([value] * len(series), index=series.index)

    @staticmethod
    def rsi(series, length):
        return pd.Series([55.0] * len(series), index=series.index)

    @staticmethod
    def atr(high, low, close, length):
        value = 1.0 if length == 14 else 2.0
        return pd.Series([value] * len(close), index=close.index)

    @staticmethod
    def supertrend(high, low, close, length, multiplier):
        return pd.DataFrame({"SUPERTd_10_3": [1] * len(close)}, index=close.index)

    @staticmethod
    def adx(high, low, close, length):
        return pd.DataFrame({"ADX_14": [30.0] * len(close)}, index=close.index)


def _make_fixture(base_price=100.0, periods=210, volume=2_000_000.0):
    idx = pd.date_range("2025-01-01", periods=periods, freq="D")
    return pd.DataFrame(
        {
            "Close": [base_price] * periods,
            "High": [base_price * 1.01] * periods,
            "Low": [base_price * 0.99] * periods,
            "Open": [base_price] * periods,
            "Volume": [volume] * periods,
        },
        index=idx,
    )


def _score_one(ticker, data, monkeypatch):
    monkeypatch.setattr(logic, "ta", _TA)
    monkeypatch.setattr(
        logic,
        "_get_benchmark_series",
        lambda symbol: pd.Series([100.0] * len(data), index=data.index),
    )
    return logic.check_institutional_fortress(
        ticker=ticker,
        data=data,
        ticker_obj=None,
        portfolio_value=1_000_000,
        risk_per_trade=0.01,
        selected_universe="NIFTY50",
        regime_data={"Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0},
    )


def test_check_institutional_fortress_identical_across_cache_population_paths(monkeypatch):
    data = _make_fixture()
    fixed_metadata = {
        "info": {"marketCap": 5_000_000_00, "debtToEquity": 0.4, "numberOfAnalystOpinions": 5},
        "news": [{"title": "steady growth", "summary": ""}],
        "cal_df": None,
        "earn_df": None,
    }

    # Path A: cache populated by a direct write — the end state a warm
    # DB-cache read (or the pre-P2 lazy fetch) would leave behind.
    _reset_caches()
    with logic._META_LOCK:
        logic._INFO_CACHE["EQUIVA.NS"] = fixed_metadata["info"]
        logic._NEWS_CACHE["EQUIVA.NS"] = fixed_metadata["news"]
        logic._CAL_CACHE["EQUIVA.NS"] = fixed_metadata["cal_df"]
        logic._EARN_CACHE["EQUIVA.NS"] = fixed_metadata["earn_df"]
    result_a = _score_one("EQUIVA.NS", data, monkeypatch)

    # Path B: cache populated via the FORTRESS-P2 concurrent prefetch path,
    # with the live fetch mocked to return the exact same metadata.
    _reset_caches()
    monkeypatch.setattr("utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: {})
    monkeypatch.setattr(logic, "_fetch_metadata_live", lambda sym: dict(fixed_metadata))
    monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", lambda records: None)
    logic.prefetch_metadata(["EQUIVA.NS"])
    result_b = _score_one("EQUIVA.NS", data, monkeypatch)

    assert result_a is not None and result_b is not None
    assert result_a == result_b
    _reset_caches()


def test_apply_advanced_scoring_ranking_identical_across_cache_population_paths(monkeypatch):
    """Two tickers with deliberately different fundamentals (so their
    scores differ and have a real ranking order), scored once with each
    cache-population path, must land on identical Score/ai_score/Verdict
    and identical relative order."""
    # Both tickers clear every quality gate (liquidity, price >= 80,
    # market cap >= 1500 Cr, debt/equity <= 2.0) so the comparison exercises
    # the fundamental-score differentiation, not a gate zeroing both to 0.
    fixtures = {
        "RANKHI.NS": (_make_fixture(base_price=200.0), {
            "info": {"marketCap": 5.0e10, "debtToEquity": 0.2},
            "news": [], "cal_df": None, "earn_df": None,
        }),
        "RANKLO.NS": (_make_fixture(base_price=90.0), {
            "info": {"marketCap": 2.0e10, "debtToEquity": 1.8},
            "news": [], "cal_df": None, "earn_df": None,
        }),
    }

    def _run(monkeypatch, use_prefetch):
        _reset_caches()
        raw_results = []
        for ticker, (data, metadata) in fixtures.items():
            if use_prefetch:
                monkeypatch.setattr(
                    "utils.db.bulk_fetch_metadata", lambda syms, max_age_hours=12: {}
                )
                monkeypatch.setattr(logic, "_fetch_metadata_live", lambda sym, m=metadata: dict(m))
                monkeypatch.setattr(logic, "upsert_ticker_metadata_cache_batch", lambda records: None)
                logic.prefetch_metadata([ticker])
            else:
                with logic._META_LOCK:
                    logic._INFO_CACHE[ticker] = metadata["info"]
                    logic._NEWS_CACHE[ticker] = metadata["news"]
                    logic._CAL_CACHE[ticker] = metadata["cal_df"]
                    logic._EARN_CACHE[ticker] = metadata["earn_df"]
            res = _score_one(ticker, data, monkeypatch)
            assert res is not None
            raw_results.append(res)
        df = pd.DataFrame(raw_results)
        scored = logic.apply_advanced_scoring(df, logic.DEFAULT_SCORING_CONFIG.copy())
        return scored.set_index("Symbol")[["Score", "ai_score", "Verdict"]]

    scored_direct = _run(monkeypatch, use_prefetch=False)
    scored_prefetch = _run(monkeypatch, use_prefetch=True)

    pd.testing.assert_frame_equal(scored_direct, scored_prefetch)
    # Sanity: the fixture is actually discriminating (not a degenerate tie).
    assert scored_direct.loc["RANKHI.NS", "Score"] != scored_direct.loc["RANKLO.NS", "Score"]
    ranking_direct = scored_direct["Score"].sort_values(ascending=False).index.tolist()
    ranking_prefetch = scored_prefetch["Score"].sort_values(ascending=False).index.tolist()
    assert ranking_direct == ranking_prefetch
    _reset_caches()
