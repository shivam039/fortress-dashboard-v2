"""Tests for the REIT/InvIT distribution-history scoring additions and the
reit_cache DB persistence layer.

Context: the REIT/InvIT tab "kept loading" for two compounding reasons —
(1) `list_reit_invits` was declared `async def` around synchronous,
potentially slow yfinance work, which freezes uvicorn's whole event loop
for the duration (same bug pattern already fixed elsewhere in this app for
the scanner/sector-pulse/MF routes), and (2) `upsert_reit_cache` was a
literal no-op placeholder, so there was no persistence layer at all — every
request (and every dev-server restart) meant a full live re-fetch across
the whole universe. Several of the configured tickers were also wrong
(guessed from marketing names rather than the actual NSE trading symbol),
which silently broke data for those specific instruments.

Separately, the user asked for past 1y/3y distribution history to show up
in the table and to factor into the conviction score, and for the universe
to cover all currently-listed Indian REITs/InvITs. These tests cover the
distribution-history derivation, the new scoring dimension, and the cache.
"""

import time

import pandas as pd

from engine.reit_invits.logic import (
    WEIGHTS,
    _call_with_timeout,
    _fetch_distribution_history,
    _score_universe,
)
from engine.reit_invits.universe import REIT_INVIT_UNIVERSE
from engine.utils.db import fetch_reit_cache, upsert_reit_cache


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_universe_tickers_are_not_the_old_wrong_guesses():
    # These marketing-name-guessed tickers were never valid NSE symbols and
    # silently broke data for the corresponding trust.
    wrong = {"BROOKFIELD.NS", "NEXUSMALLS.NS", "POWERTRAN.NS", "NHAI.NS", "BHINVIT.NS"}
    assert wrong.isdisjoint(REIT_INVIT_UNIVERSE.keys())


def test_universe_has_at_least_the_known_listed_trusts():
    expected = {
        "EMBASSY.NS", "MINDSPACE.NS", "BIRET.NS", "NXST.NS", "KRT.NS",
        "INDIGRID.NS", "PGINVIT.NS", "IRBINVIT.NS", "NHIT.NS",
        "INDUSINVIT.NS", "RIIT.NS",
    }
    assert expected.issubset(REIT_INVIT_UNIVERSE.keys())


def _fake_dividends(amount_days_ago_pairs):
    """Build a fake yfinance-style dividends Series from a list of
    (amount, days_ago) pairs — a plain dict can't hold repeated amounts as
    keys, so this takes pairs instead."""
    today = pd.Timestamp.today().normalize()
    dates = [today - pd.Timedelta(days=d) for _, d in amount_days_ago_pairs]
    values = [amt for amt, _ in amount_days_ago_pairs]
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def test_fetch_distribution_history_sums_trailing_1y_and_3y(monkeypatch):
    # Four quarterly payouts of 5 in the last year, four more of 4 the year
    # before that (baseline for the growth calc), for a total of 8 payouts
    # across ~2 years — well within the 3y window.
    divs = _fake_dividends([
        (5.0, 30), (5.0, 120), (5.0, 210), (5.0, 300),   # last ~1y
        (4.0, 400), (4.0, 490), (4.0, 580), (4.0, 670),  # ~1-2y ago
    ])

    class _FakeTicker:
        dividends = divs

    monkeypatch.setattr(
        "engine.reit_invits.logic.yf.Ticker",
        lambda symbol: _FakeTicker(),
    )

    out = _fetch_distribution_history("FAKE.NS")
    assert out["distributions_1y"] == 20.0
    assert out["distribution_count_1y"] == 4
    assert out["distributions_3y"] == 36.0


def test_fetch_distribution_history_empty_series_returns_all_none(monkeypatch):
    class _FakeTicker:
        dividends = pd.Series(dtype=float)

    monkeypatch.setattr(
        "engine.reit_invits.logic.yf.Ticker",
        lambda symbol: _FakeTicker(),
    )

    out = _fetch_distribution_history("NEWFUND.NS")
    assert out == {
        "distributions_1y": None,
        "distributions_3y": None,
        "distributions_3y_avg": None,
        "distribution_count_1y": None,
        "distribution_growth_3y_pct": None,
    }


def test_fetch_distribution_history_handles_exception_gracefully(monkeypatch):
    def _raise(symbol):
        raise RuntimeError("network error")

    monkeypatch.setattr("engine.reit_invits.logic.yf.Ticker", _raise)

    out = _fetch_distribution_history("BROKEN.NS")
    assert out["distributions_1y"] is None


def test_score_universe_includes_distribution_growth_dimension():
    records = [
        {
            "symbol": "TEST1", "price": 100, "yield_pct": 8.0,
            "returns_1y": 15.0, "returns_1m": 2.0, "volatility_30d": 12.0,
            "max_drawdown_1y": -5.0, "returns_3m": 5.0,
            "distributions_1y": 8.0, "distribution_growth_3y_pct": 12.0,
        },
        {
            "symbol": "TEST2", "price": 50, "yield_pct": 5.0,
            "returns_1y": 5.0, "returns_1m": -1.0, "volatility_30d": 20.0,
            "max_drawdown_1y": -15.0, "returns_3m": 1.0,
            "distributions_1y": 2.5, "distribution_growth_3y_pct": -10.0,
        },
    ]
    scored = _score_universe(records)
    for r in scored:
        assert "distribution_growth_score" in r["score_breakdown"]
        assert 0 <= r["score_breakdown"]["distribution_growth_score"] <= 100
    # TEST1 grew its distribution, TEST2 shrank it — TEST1 should rank higher.
    t1 = next(r for r in scored if r["symbol"] == "TEST1")
    t2 = next(r for r in scored if r["symbol"] == "TEST2")
    assert t1["score_breakdown"]["distribution_growth_score"] > t2["score_breakdown"]["distribution_growth_score"]


def test_score_universe_neutral_growth_score_for_new_listing_without_3y_history():
    records = [
        {
            "symbol": "NEWFUND", "price": 100, "yield_pct": 8.0,
            "returns_1y": 15.0, "returns_1m": 2.0, "volatility_30d": 12.0,
            "max_drawdown_1y": -5.0, "returns_3m": 5.0,
            "distributions_1y": 8.0, "distribution_growth_3y_pct": None,
        },
    ]
    scored = _score_universe(records)
    assert scored[0]["score_breakdown"]["distribution_growth_score"] == 50.0
    # A missing 3y-growth figure alone shouldn't be treated as missing data
    # for confidence purposes — it's expected for anything under 3y old.
    assert scored[0]["confidence_score"] > 0


def test_score_universe_assigns_conviction_label_and_emoji():
    records = [{
        "symbol": "TEST1", "price": 100, "yield_pct": 8.0,
        "returns_1y": 15.0, "returns_1m": 2.0, "volatility_30d": 12.0,
        "max_drawdown_1y": -5.0, "returns_3m": 5.0,
    }]
    scored = _score_universe(records)
    assert scored[0]["conviction_label"] in {"STRONG BUY", "BUY", "HOLD", "UNDERPERFORMER", "AVOID"}
    assert scored[0]["conviction_emoji"]


def test_score_universe_valuation_note_reflects_nav_premium():
    records = [
        {"symbol": "DISCOUNT", "price": 90, "nav_premium_pct": -10.0},
        {"symbol": "PREMIUM", "price": 130, "nav_premium_pct": 25.0},
        {"symbol": "FAIR", "price": 100, "nav_premium_pct": 1.0},
    ]
    scored = _score_universe(records)
    by_symbol = {r["symbol"]: r for r in scored}
    assert "below NAV" in by_symbol["DISCOUNT"]["valuation_note"]
    assert "rich premium" in by_symbol["PREMIUM"]["valuation_note"]
    assert "fairly valued" in by_symbol["FAIR"]["valuation_note"]


def test_score_universe_no_price_gets_null_label_not_a_crash():
    records = [{"symbol": "NODATA", "price": None}]
    scored = _score_universe(records)
    assert scored[0]["conviction_label"] is None
    assert scored[0]["valuation_note"] is None


def _fake_reit_record(symbol="ZZTESTREIT1"):
    return {
        "symbol": symbol,
        "name": "Test REIT",
        "asset_class": "REIT",
        "price": 350.5,
        "conviction_score": 72.0,
        "conviction_label": "BUY",
        "distributions_1y": 18.5,
        "distributions_3y": 52.0,
    }


def test_reit_cache_round_trip():
    record = _fake_reit_record("ZZTESTREIT_RT")
    upsert_reit_cache([record])

    fresh = fetch_reit_cache(max_age_hours=24)
    match = next((r for r in fresh if r.get("symbol") == "ZZTESTREIT_RT"), None)
    assert match is not None
    assert match["conviction_label"] == "BUY"
    assert match["distributions_1y"] == 18.5


def test_reit_cache_excludes_stale_rows():
    upsert_reit_cache([_fake_reit_record("ZZTESTREIT_STALE")])

    fresh = fetch_reit_cache(max_age_hours=24)
    assert any(r.get("symbol") == "ZZTESTREIT_STALE" for r in fresh)

    # A just-written row can never satisfy "updated in the future".
    stale = fetch_reit_cache(max_age_hours=-1)
    assert not any(r.get("symbol") == "ZZTESTREIT_STALE" for r in stale)


def test_reit_cache_upsert_overwrites():
    upsert_reit_cache([_fake_reit_record("ZZTESTREIT_OW")])
    updated = _fake_reit_record("ZZTESTREIT_OW")
    updated["conviction_score"] = 40.0
    updated["conviction_label"] = "AVOID"
    upsert_reit_cache([updated])

    fresh = fetch_reit_cache(max_age_hours=24)
    match = next(r for r in fresh if r.get("symbol") == "ZZTESTREIT_OW")
    assert match["conviction_score"] == 40.0
    assert match["conviction_label"] == "AVOID"


def test_reit_cache_empty_list_is_a_noop():
    # Must not raise.
    upsert_reit_cache([])


def test_call_with_timeout_bounds_a_hanging_call():
    """yfinance's Ticker.info/.dividends expose no timeout of their own —
    on a slow/rate-limited connection a single call has been observed
    taking the better part of a minute, which is most of build_reit_frame's
    whole 45s batch budget. _call_with_timeout must give up on a stuck call
    well before that, rather than actually waiting it out."""
    start = time.monotonic()
    result = _call_with_timeout(lambda: time.sleep(5), timeout_s=0.2, default="TIMED_OUT")
    elapsed = time.monotonic() - start
    assert result == "TIMED_OUT"
    assert elapsed < 1.0, f"took {elapsed:.2f}s to give up on a 0.2s timeout"


def test_call_with_timeout_returns_the_real_result_when_fast_enough():
    result = _call_with_timeout(lambda: 42, timeout_s=5)
    assert result == 42


def test_call_with_timeout_swallows_exceptions_and_returns_default():
    def _raise():
        raise RuntimeError("boom")

    result = _call_with_timeout(_raise, timeout_s=5, default="fallback")
    assert result == "fallback"


def test_get_or_fetch_frame_does_not_db_cache_a_degraded_live_fetch(monkeypatch):
    """A live fetch where most symbols come back as placeholder/error rows
    (batch timeout, provider outage — see reit_invits/logic.py's
    _BATCH_TIMEOUT_S) must not get written into the DB-backed reit_cache
    table. Doing so would overwrite any still-good previously cached data
    with blanks and lock every viewer into that for _CACHE_MAX_AGE_HOURS."""
    # These are imported under the bare module names ("reit_invits.logic",
    # "routers.reit_invits", "utils.db") that engine/main.py's sys.path
    # trick makes the *actual* names FastAPI's app loads them under — not
    # the "engine.*"-prefixed names used elsewhere in this file, which are
    # loaded as separate module objects with their own separate globals.
    import reit_invits.logic as reit_logic
    import routers.reit_invits as reit_router
    import utils.db as db_mod

    reit_router._cached_frame = None
    reit_router._cache_ts = None
    reit_router._cache_is_degraded = False

    degraded_frame = [
        {"symbol": "A.NS", "price": None, "risk_flags": ["fetch_timeout"]},
        {"symbol": "B.NS", "price": None, "risk_flags": ["fetch_timeout"]},
        {"symbol": "C.NS", "price": 100.0, "risk_flags": []},
    ]
    monkeypatch.setattr(reit_logic, "build_reit_frame", lambda: degraded_frame)
    monkeypatch.setattr(db_mod, "fetch_reit_cache", lambda max_age_hours: [])

    upsert_calls = []
    monkeypatch.setattr(
        db_mod, "upsert_reit_cache", lambda records: upsert_calls.append(records)
    )

    result = reit_router._get_or_fetch_frame()

    assert result == degraded_frame  # still answers this one request
    assert upsert_calls == []  # but does not persist it to the DB cache
    assert reit_router._cache_is_degraded is True


def test_get_or_fetch_frame_short_circuits_repeat_requests_during_an_outage(monkeypatch):
    """The in-process cache DOES hold on to a degraded frame (unlike the DB
    cache) so that repeat requests within _DEGRADED_CACHE_MAX_AGE_MINUTES
    are served from it instead of each triggering their own live-fetch
    attempt. build_reit_frame() spins up roughly two dozen threads per
    attempt (an outer pool of 6, plus up to two _call_with_timeout
    single-use executors per symbol) — without this short-circuit, every
    incoming request during a sustained outage would trigger its own
    attempt, and threads still blocked on a stalled connection when their
    timeout fires are abandoned rather than killed. That unbounded thread
    growth under real traffic is exactly the shape of the "Web Service
    exceeded its memory limit" restarts this is meant to prevent."""
    import reit_invits.logic as reit_logic
    import routers.reit_invits as reit_router
    import utils.db as db_mod

    reit_router._cached_frame = None
    reit_router._cache_ts = None
    reit_router._cache_is_degraded = False

    degraded_frame = [{"symbol": "A.NS", "price": None, "risk_flags": ["fetch_timeout"]}]
    fetch_calls = []
    monkeypatch.setattr(
        reit_logic, "build_reit_frame", lambda: (fetch_calls.append(1), degraded_frame)[1]
    )
    monkeypatch.setattr(db_mod, "fetch_reit_cache", lambda max_age_hours: [])
    monkeypatch.setattr(db_mod, "upsert_reit_cache", lambda records: None)

    first = reit_router._get_or_fetch_frame()
    second = reit_router._get_or_fetch_frame()

    assert first == degraded_frame
    assert second == degraded_frame
    assert len(fetch_calls) == 1, "second request should be served from cache, not refetch live"


def test_get_or_fetch_frame_does_cache_a_healthy_live_fetch(monkeypatch):
    """Sanity check for the tests above: a fetch that mostly succeeded must
    still be cached as before, with the normal long TTL — the
    degraded-frame handling should only ever change behavior for a
    degraded fetch, never for a normal, healthy one."""
    import reit_invits.logic as reit_logic
    import routers.reit_invits as reit_router
    import utils.db as db_mod

    reit_router._cached_frame = None
    reit_router._cache_ts = None
    reit_router._cache_is_degraded = False

    healthy_frame = [
        {"symbol": "A.NS", "price": 100.0, "risk_flags": []},
        {"symbol": "B.NS", "price": 200.0, "risk_flags": []},
        {"symbol": "C.NS", "price": 300.0, "risk_flags": []},
        {"symbol": "D.NS", "price": None, "risk_flags": ["fetch_timeout"]},
    ]
    monkeypatch.setattr(reit_logic, "build_reit_frame", lambda: healthy_frame)
    monkeypatch.setattr(db_mod, "fetch_reit_cache", lambda max_age_hours: [])

    upsert_calls = []
    monkeypatch.setattr(
        db_mod, "upsert_reit_cache", lambda records: upsert_calls.append(records)
    )

    result = reit_router._get_or_fetch_frame()

    assert result == healthy_frame
    assert upsert_calls == [healthy_frame]
    assert reit_router._cached_frame == healthy_frame
    assert reit_router._cache_ts is not None
    assert reit_router._cache_is_degraded is False
