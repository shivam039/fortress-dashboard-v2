"""Tests for the US Investing scoring pipeline and its (new) DB-backed cache.

Context: reviewing US_INVESTING_SCORING.md against the actual code turned up
several real gaps, fixed here:
  1. get_us_detail() scored a single instrument against a "peer group" of
     just itself, so every single-symbol lookup returned a perfect 100 on
     every dimension regardless of the instrument's real metrics.
  2. The module docstring claimed valuation ranks P/E "vs sector median";
     the code pooled every instrument's P/E together with no sector
     grouping at all.
  3. upsert_us_cache() was a literal no-op placeholder — there was no DB
     persistence layer, so every process restart meant the next request
     re-fetched the whole 31-symbol universe live before anything could be
     served.
  4. downside_protection inverted an already-correctly-signed metric
     (max_drawdown_1y is stored as a negative number, so a shallower loss
     is already the *higher* raw value) — the fund with the *better*
     drawdown scored *worse* downside protection than one with a deep loss.
This file also has no prior test coverage at all (unlike reit_invits,
which test_reit_scoring.py/test_reit_distributions.py already covered) —
these tests establish a baseline alongside the fixes above.
"""

import pytest

from us_investing.logic import (
    WEIGHTS,
    _MIN_SECTOR_PEERS_FOR_VALUATION,
    _pct_rank,
    _score_universe,
)
from utils.db import fetch_us_cache, upsert_us_cache


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_pct_rank_single_peer_is_neutral_not_a_trivial_100():
    assert _pct_rank(8.0, [8.0]) == 50.0
    assert _pct_rank(8.0, [8.0, 4.0]) == 100.0
    assert _pct_rank(4.0, [8.0, 4.0]) == 50.0


def test_pct_rank_higher_is_better_false_inverts_correctly():
    # Lower value should rank HIGHER when higher_is_better=False: with 2
    # peers, count(peers <= value)/n is 1/2 for the lower value (only
    # itself) and 2/2 for the higher one, so inverted scores are 50/0 —
    # not 100/0, since "count <= self" always includes at least itself.
    assert _pct_rank(4.0, [4.0, 8.0], higher_is_better=False) == 50.0
    assert _pct_rank(8.0, [4.0, 8.0], higher_is_better=False) == 0.0


def test_score_universe_downside_protection_rewards_shallower_drawdown():
    """The fund with the SHALLOWER (better) drawdown must score HIGHER
    downside_protection than one with a deeper loss — this was inverted
    before the fix (see module docstring point 4)."""
    records = [
        {"symbol": "SHALLOW", "price": 100, "max_drawdown_1y": -5.0},
        {"symbol": "DEEP", "price": 100, "max_drawdown_1y": -30.0},
    ]
    scored = _score_universe(records)
    by_symbol = {r["symbol"]: r for r in scored}
    shallow_dp = by_symbol["SHALLOW"]["score_breakdown"]["downside_protection"]
    deep_dp = by_symbol["DEEP"]["score_breakdown"]["downside_protection"]
    assert shallow_dp > deep_dp
    assert shallow_dp == 100.0
    assert deep_dp == 50.0


def test_score_universe_valuation_ranks_within_sector_not_pooled():
    """A cheap stock in an expensive sector should NOT get penalized for
    the whole universe's unrelated, richer-valued sectors — valuation
    should be ranked against same-sector peers when there are enough of
    them (_MIN_SECTOR_PEERS_FOR_VALUATION)."""
    def _rec(symbol, sector, pe):
        return {"symbol": symbol, "price": 100, "sector": sector, "pe_ratio": pe}

    records = [
        # Tech sector: expensive (30-50 PE), 3 peers -> real sector grouping applies.
        _rec("TECH_LOW", "Technology", 30.0),
        _rec("TECH_MID", "Technology", 40.0),
        _rec("TECH_HIGH", "Technology", 50.0),
        # Energy: cheap (8-12 PE), 3 peers.
        _rec("NRG_LOW", "Energy", 8.0),
        _rec("NRG_MID", "Energy", 10.0),
        _rec("NRG_HIGH", "Energy", 12.0),
    ]
    scored = _score_universe(records)
    by_symbol = {r["symbol"]: r for r in scored}

    # TECH_LOW (PE 30, cheapest of its OWN sector) should rank well within
    # tech (lower PE = better = higher valuation score), not be penalized
    # for being pricier than every Energy name if pooled together.
    tech_low_valuation = by_symbol["TECH_LOW"]["score_breakdown"]["valuation"]
    nrg_high_valuation = by_symbol["NRG_HIGH"]["score_breakdown"]["valuation"]
    # TECH_LOW is the cheapest within Technology -> pct_rank(30, [30,40,50],
    # higher_is_better=False): count(peers <= 30)/3 = 1/3, inverted =
    # (1 - 1/3)*100 = 66.7 (the max any single instrument can reach in a
    # 3-peer group, since "count <= self" always includes itself).
    # NRG_HIGH is the priciest within Energy -> pct_rank(12, [8,10,12],
    # higher_is_better=False): count(<=12)/3 = 3/3, inverted = 0.
    assert tech_low_valuation == pytest.approx(66.7, abs=0.1)
    assert nrg_high_valuation == 0.0
    # The key behavior under test: TECH_LOW (cheapest within its own richly
    # -valued sector) still scores far better than NRG_HIGH (priciest
    # within its own cheap sector) — sector-scoping, not raw pooled PE,
    # decides the ranking.
    assert tech_low_valuation > nrg_high_valuation


def test_score_universe_valuation_falls_back_to_whole_pool_for_thin_sector():
    """A sector with fewer than _MIN_SECTOR_PEERS_FOR_VALUATION same-sector
    peers with a valid P/E should fall back to ranking against the whole
    universe's P/E pool instead of a too-thin (or single-instrument, i.e.
    the old bug's shape) same-sector comparison."""
    records = [
        {"symbol": "LONER", "price": 100, "sector": "Utilities", "pe_ratio": 15.0},
        {"symbol": "A", "price": 100, "sector": "Technology", "pe_ratio": 10.0},
        {"symbol": "B", "price": 100, "sector": "Technology", "pe_ratio": 20.0},
        {"symbol": "C", "price": 100, "sector": "Technology", "pe_ratio": 30.0},
    ]
    scored = _score_universe(records)
    by_symbol = {r["symbol"]: r for r in scored}
    # LONER is the only Utilities stock (0 other same-sector peers) -> not
    # enough for a sector-scoped rank, falls back to the whole pool
    # [15, 10, 20, 30]: count(peers <= 15)/4 = {15, 10}/4 = 0.5, inverted
    # (higher_is_better=False) = (1 - 0.5) * 100 = 50.0.
    assert by_symbol["LONER"]["score_breakdown"]["valuation"] == 50.0


def _fake_us_record(symbol="ZZTESTUS1"):
    return {
        "symbol": symbol,
        "name": "Test US Stock",
        "asset_class": "US_STOCK",
        "price": 150.25,
        "conviction_score": 68.0,
        "score_breakdown": {"return_score": 70.0},
    }


def test_us_cache_round_trip():
    record = _fake_us_record("ZZTESTUS_RT")
    upsert_us_cache([record])

    fresh = fetch_us_cache(max_age_hours=24)
    match = next((r for r in fresh if r.get("symbol") == "ZZTESTUS_RT"), None)
    assert match is not None
    assert match["conviction_score"] == 68.0
    assert match["price"] == 150.25


def test_us_cache_excludes_stale_rows():
    upsert_us_cache([_fake_us_record("ZZTESTUS_STALE")])

    fresh = fetch_us_cache(max_age_hours=24)
    assert any(r.get("symbol") == "ZZTESTUS_STALE" for r in fresh)

    # A just-written row can never satisfy "updated in the future".
    stale = fetch_us_cache(max_age_hours=-1)
    assert not any(r.get("symbol") == "ZZTESTUS_STALE" for r in stale)


def test_us_cache_upsert_overwrites():
    upsert_us_cache([_fake_us_record("ZZTESTUS_OW")])
    updated = _fake_us_record("ZZTESTUS_OW")
    updated["conviction_score"] = 12.0
    upsert_us_cache([updated])

    fresh = fetch_us_cache(max_age_hours=24)
    match = next(r for r in fresh if r.get("symbol") == "ZZTESTUS_OW")
    assert match["conviction_score"] == 12.0


def test_us_cache_empty_list_is_a_noop():
    # Must not raise.
    upsert_us_cache([])


def test_get_or_fetch_frame_does_not_db_cache_a_degraded_live_fetch(monkeypatch):
    """Same protection as reit_invits' equivalent test (see
    test_reit_distributions.py) — a live fetch where most symbols come back
    with no price must not get written into the DB-backed
    us_investing_cache table, or it would overwrite any still-good
    previously cached data with blanks."""
    import routers.us_investing as us_router
    import us_investing.logic as us_logic
    import utils.db as db_mod

    us_router._cached_frame = None
    us_router._cache_ts = None

    degraded_frame = [
        {"symbol": "A", "price": None},
        {"symbol": "B", "price": None},
        {"symbol": "C", "price": 100.0},
    ]
    monkeypatch.setattr(us_logic, "build_us_frame", lambda include_inr=True: degraded_frame)
    monkeypatch.setattr(db_mod, "fetch_us_cache", lambda max_age_hours: [])

    upsert_calls = []
    monkeypatch.setattr(db_mod, "upsert_us_cache", lambda records: upsert_calls.append(records))

    result = us_router._get_or_fetch_frame()

    assert result == degraded_frame  # still answers this one request
    assert upsert_calls == []  # but does not persist it to the DB cache


def test_get_or_fetch_frame_does_cache_a_healthy_live_fetch(monkeypatch):
    import routers.us_investing as us_router
    import us_investing.logic as us_logic
    import utils.db as db_mod

    us_router._cached_frame = None
    us_router._cache_ts = None

    healthy_frame = [
        {"symbol": "A", "price": 100.0},
        {"symbol": "B", "price": 200.0},
        {"symbol": "C", "price": 300.0},
        {"symbol": "D", "price": None},
    ]
    monkeypatch.setattr(us_logic, "build_us_frame", lambda include_inr=True: healthy_frame)
    monkeypatch.setattr(db_mod, "fetch_us_cache", lambda max_age_hours: [])

    upsert_calls = []
    monkeypatch.setattr(db_mod, "upsert_us_cache", lambda records: upsert_calls.append(records))

    result = us_router._get_or_fetch_frame()

    assert result == healthy_frame
    assert upsert_calls == [healthy_frame]
    assert us_router._cached_frame == healthy_frame


def test_get_us_detail_endpoint_uses_full_universe_peers_not_itself(monkeypatch):
    """GET /api/us-investing/{symbol} must rank the requested instrument
    against the other instruments in the cached frame, not a "peer group"
    of just itself (the old us_investing.logic.get_us_detail() bug — see
    US_INVESTING_SCORING.md §7)."""
    import routers.us_investing as us_router

    us_router._cached_frame = None
    us_router._cache_ts = None

    # AAPL is a real key in FULL_UNIVERSE — the endpoint 404s fast on an
    # unknown symbol before ever calling _get_or_fetch_frame.
    weak = {
        "symbol": "AAPL", "price": 100, "returns_1y": -30.0, "returns_1m": -8.0,
        "volatility_30d": 60.0, "max_drawdown_1y": -50.0, "returns_3m": -15.0,
    }
    strong_peers = [
        {
            "symbol": f"PEER{i}", "price": 100, "returns_1y": 40.0, "returns_1m": 10.0,
            "volatility_30d": 10.0, "max_drawdown_1y": -3.0, "returns_3m": 12.0,
        }
        for i in range(4)
    ]
    scored_frame = _score_universe([weak] + strong_peers)

    monkeypatch.setattr(us_router, "_get_or_fetch_frame", lambda include_inr=True: scored_frame)

    result = us_router.get_us_detail("AAPL")
    assert result["symbol"] == "AAPL"
    assert result["score_breakdown"]["downside_protection"] < 50.0
    assert result["conviction_score"] < 50.0
