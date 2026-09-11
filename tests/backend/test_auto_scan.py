"""FORTRESS-E3: automated multi-universe EOD scanning.

DATA HEALTH -> MULTI-UNIVERSE SCAN -> E1 -> T1 -> E2 -> MATURATION ->
DAILY SUMMARY, orchestrated by research.auto_scan.run_daily_auto_scan().
Orchestration tests inject a fake execute_scan_fn (no real indicator
computation, matching test_v4_end_to_end.py / test_circuit_breaker_empty_data.py's
own established convention of monkeypatching main.check_institutional_fortress
rather than exercising it); one test uses the real main.execute_scan (with
only the market-data boundary mocked) to prove a genuine no-scoring-change
guarantee. No live network access anywhere in this file.
"""
import inspect
import uuid

import main as main_mod
import pandas as pd
import research.auto_scan as auto_scan
import routers.auto_scan as auto_scan_router
import utils.db as db
import utils.market_data_provider as mdp
from research.auto_scan import (
    build_symbol_union,
    check_data_health,
    resolve_configured_universes,
    run_daily_auto_scan,
)
from utils.db import (
    fetch_auto_scan_run,
    fetch_universe_memberships,
    record_universe_memberships,
)

_STUB_UNIVERSES = {
    "E3 Universe A": ["ZZE3SHARED.NS", "ZZE3A.NS"],
    "E3 Universe B": ["ZZE3SHARED.NS", "ZZE3B.NS"],
}
# auto_scan_runs/symbol_universe_membership are keyed by trading_date as a
# plain string, so a run-unique tag here (not a real calendar date) keeps
# repeated local pytest invocations against the same persistent SQLite test
# DB from colliding with rows a prior invocation already committed —
# without this, a rerun would see "already scanned" and skip, exactly the
# idempotency this story tests, but for the wrong reason.
_TAG = uuid.uuid4().hex[:8]


def _date(n: int) -> str:
    return f"2025-04-{n:02d}-{_TAG}"


_HEALTHY = {
    "healthy": True, "issues": [], "provider_status": {"ohlcv_source": "indstocks"},
    "bhavcopy_status": None, "canary_symbol": "ZZE3A.NS", "canary_rows": 220,
    "resolvable_universes": ["E3 Universe A", "E3 Universe B"], "unresolved_universes": [],
}


def _hist(n=220):
    return pd.DataFrame({"Close": range(n)})


def _fake_execute_scan(quality_pass_map, tripped=False, drop=()):
    """Stand-in for main.execute_scan's (req, tickers_override, run_meta,
    universe_membership) contract, so orchestration tests never need real
    indicator computation. `drop` simulates one-failed-symbol-does-not-
    corrupt-the-rest: those symbols count toward scanned/failed but produce
    no scored record."""
    calls = {"n": 0}

    def _fn(req, tickers_override=None, run_meta=None, universe_membership=None):
        calls["n"] += 1
        scored = [s for s in (tickers_override or []) if s not in drop]
        records = [{"Symbol": s, "Score": 80.0, "Quality_Gate_Pass": quality_pass_map.get(s, True)} for s in scored]
        if run_meta is not None:
            run_meta.update({
                "scan_id": 1, "signals_written": len(records),
                "research_observations_result": {"inserted": len(records), "duplicates": 0},
                "scanned": len(tickers_override or []), "failed": len(drop),
                "circuit_breaker_tripped": tripped,
            })
        return records

    _fn.calls = calls
    return _fn


def _patch_e2_and_maturation(monkeypatch, opened=0, closed=0, manage_closed=0):
    monkeypatch.setattr(
        "paper_trading.policy_engine.run_paper_portfolio",
        lambda **k: {"opened": opened, "closed_today": closed},
    )
    monkeypatch.setattr(
        "paper_trading.policy_engine.manage_open_positions",
        lambda **k: {"closed": manage_closed, "open_before": 0},
    )
    monkeypatch.setattr(
        "research.prospective_store.mature_pending_outcomes",
        lambda **k: {"checked": 0, "matured": 0, "unavailable": 0, "matured_by_horizon": {}},
    )


# ── 1. multiple universes resolve + overlap dedup ───────────────────────────

def test_build_symbol_union_deduplicates_overlap(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    union, membership = build_symbol_union(["E3 Universe A", "E3 Universe B"])
    assert union.count("ZZE3SHARED.NS") == 1
    assert sorted(union) == ["ZZE3A.NS", "ZZE3B.NS", "ZZE3SHARED.NS"]
    assert sorted(membership["ZZE3SHARED.NS"]) == ["E3 Universe A", "E3 Universe B"]
    assert membership["ZZE3A.NS"] == ["E3 Universe A"]


def test_resolve_configured_universes_env_and_default(monkeypatch):
    monkeypatch.delenv("FORTRESS_AUTO_SCAN_UNIVERSES", raising=False)
    assert resolve_configured_universes() == list(auto_scan.DEFAULT_AUTO_SCAN_UNIVERSES)
    monkeypatch.setenv("FORTRESS_AUTO_SCAN_UNIVERSES", "Nifty 50, Nifty 100")
    assert resolve_configured_universes() == ["Nifty 50", "Nifty 100"]


# ── data-health gate ─────────────────────────────────────────────────────────

def test_check_data_health_healthy(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(mdp, "provider_status", lambda: {"ohlcv_source": "indstocks"})
    health = check_data_health(_date(1), ["E3 Universe A"], get_ohlcv_fn=lambda s, p: _hist(220))
    assert health["healthy"] is True
    assert health["unresolved_universes"] == []


def test_check_data_health_insufficient_history_aborts(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(mdp, "provider_status", lambda: {"ohlcv_source": "indstocks"})
    health = check_data_health(_date(1), ["E3 Universe A"], get_ohlcv_fn=lambda s, p: _hist(50))
    assert health["healthy"] is False
    assert any("insufficient_history_depth" in i for i in health["issues"])


def test_check_data_health_bhavcopy_not_ready_aborts(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(mdp, "provider_status", lambda: {"ohlcv_source": "bhavcopy"})
    monkeypatch.setattr(db, "get_bhavcopy_fetch_status", lambda d: "not_yet_published")
    health = check_data_health(_date(1), ["E3 Universe A"], get_ohlcv_fn=lambda s, p: _hist(220))
    assert health["healthy"] is False
    assert any("bhavcopy_not_ready" in i for i in health["issues"])


def test_check_data_health_unresolved_universe_reported_but_not_fatal(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(mdp, "provider_status", lambda: {"ohlcv_source": "indstocks"})
    health = check_data_health(
        _date(1), ["E3 Universe A", "Nonexistent Universe"], get_ohlcv_fn=lambda s, p: _hist(220),
    )
    assert "Nonexistent Universe" in health["unresolved_universes"]
    assert health["healthy"] is True


# ── membership persistence ───────────────────────────────────────────────────

def test_record_universe_memberships_idempotent():
    entries = [
        {"trading_date": _date(2), "symbol": "ZZE3MEMB.NS", "universe": "E3 Universe A", "run_id": "r1"},
        {"trading_date": _date(2), "symbol": "ZZE3MEMB.NS", "universe": "E3 Universe B", "run_id": "r1"},
    ]
    written1 = record_universe_memberships(entries)
    written2 = record_universe_memberships(entries)
    assert written1 == 2
    assert written2 == 0
    rows = fetch_universe_memberships(trading_date=_date(2), symbol="ZZE3MEMB.NS")
    assert sorted(r["universe"] for r in rows) == ["E3 Universe A", "E3 Universe B"]


# ── orchestration ─────────────────────────────────────────────────────────

def test_run_daily_auto_scan_happy_path_scores_union_once_and_isolates_one_failure(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: _HEALTHY)
    fake_scan = _fake_execute_scan(
        {"ZZE3SHARED.NS": True, "ZZE3A.NS": False, "ZZE3B.NS": True}, drop=("ZZE3B.NS",),
    )
    _patch_e2_and_maturation(monkeypatch, opened=2, closed=1)

    summary = run_daily_auto_scan(
        trading_date=_date(3), universes=["E3 Universe A", "E3 Universe B"],
        get_ohlcv_fn=lambda s, p: _hist(220), execute_scan_fn=fake_scan,
    )

    assert fake_scan.calls["n"] == 1  # union scored ONCE, not once per universe
    assert summary["unique_symbols"] == 3
    assert summary["successfully_scored"] == 2  # ZZE3B.NS's failure didn't corrupt the other two
    assert summary["unscorable"] == 1
    assert summary["signals_generated"] == 1  # only ZZE3SHARED.NS passed the quality gate among the scored ones
    assert summary["research_observations_inserted"] == 2
    assert summary["paper_positions_opened"] == 2
    assert summary["paper_positions_closed"] == 1
    assert summary["run_status"] == "COMPLETE"


def test_run_daily_auto_scan_persists_membership_for_overlapping_symbol(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: _HEALTHY)
    fake_scan = _fake_execute_scan({"ZZE3SHARED.NS": True, "ZZE3A.NS": True, "ZZE3B.NS": True})
    _patch_e2_and_maturation(monkeypatch)

    trading_date = _date(9)
    run_daily_auto_scan(
        trading_date=trading_date, universes=["E3 Universe A", "E3 Universe B"], execute_scan_fn=fake_scan,
    )

    rows = fetch_universe_memberships(trading_date=trading_date, symbol="ZZE3SHARED.NS")
    assert sorted(r["universe"] for r in rows) == ["E3 Universe A", "E3 Universe B"]


def test_run_daily_auto_scan_unhealthy_data_aborts_before_scanning(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: {
        **_HEALTHY, "healthy": False, "issues": ["bhavcopy_not_ready:error"],
    })
    fake_scan = _fake_execute_scan({"ZZE3A.NS": True})
    _patch_e2_and_maturation(monkeypatch, manage_closed=0)

    summary = run_daily_auto_scan(trading_date=_date(4), universes=["E3 Universe A"], execute_scan_fn=fake_scan)

    assert fake_scan.calls["n"] == 0  # never scanned — no partial evidence created
    assert summary["run_status"] == "FAILED"
    assert summary["successfully_scored"] == 0
    assert summary["signals_generated"] == 0
    assert summary["research_observations_inserted"] == 0
    assert summary["paper_positions_opened"] == 0  # existing positions may still be managed, nothing new opened


def test_run_daily_auto_scan_circuit_breaker_tripped_marks_failed_and_blocks_new_entries(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: _HEALTHY)
    fake_scan = _fake_execute_scan({"ZZE3A.NS": True}, tripped=True)

    run_calls = {"n": 0}
    monkeypatch.setattr("paper_trading.policy_engine.run_paper_portfolio", lambda **k: run_calls.__setitem__("n", run_calls["n"] + 1) or {"opened": 5, "closed_today": 0})
    monkeypatch.setattr("paper_trading.policy_engine.manage_open_positions", lambda **k: {"closed": 0, "open_before": 0})
    monkeypatch.setattr("research.prospective_store.mature_pending_outcomes", lambda **k: {"checked": 0, "matured": 0, "unavailable": 0, "matured_by_horizon": {}})

    summary = run_daily_auto_scan(trading_date=_date(5), universes=["E3 Universe A"], execute_scan_fn=fake_scan)

    assert summary["circuit_breaker"] == "triggered"
    assert summary["run_status"] == "FAILED"
    assert summary["paper_positions_opened"] == 0
    assert run_calls["n"] == 0  # run_paper_portfolio (which opens new positions) was never even called


def test_run_daily_auto_scan_unresolved_universe_marks_degraded(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: {
        **_HEALTHY, "resolvable_universes": ["E3 Universe A"], "unresolved_universes": ["Ghost Universe"],
    })
    fake_scan = _fake_execute_scan({"ZZE3SHARED.NS": True, "ZZE3A.NS": True})
    _patch_e2_and_maturation(monkeypatch)

    summary = run_daily_auto_scan(
        trading_date=_date(6), universes=["E3 Universe A", "Ghost Universe"], execute_scan_fn=fake_scan,
    )

    assert fake_scan.calls["n"] == 1  # the resolvable universe still gets scanned
    assert summary["run_status"] == "DEGRADED"
    assert summary["unresolved_universes"] == ["Ghost Universe"]


def test_run_daily_auto_scan_rerun_same_date_is_idempotent_and_never_fabricates(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: {
        **_HEALTHY, "resolvable_universes": ["E3 Universe A"],
    })
    fake_scan = _fake_execute_scan({"ZZE3A.NS": True})
    _patch_e2_and_maturation(monkeypatch, opened=1)

    trading_date = _date(7)
    first = run_daily_auto_scan(trading_date=trading_date, universes=["E3 Universe A"], execute_scan_fn=fake_scan)
    second = run_daily_auto_scan(trading_date=trading_date, universes=["E3 Universe A"], execute_scan_fn=fake_scan)

    assert first["run_status"] == "COMPLETE"
    assert fake_scan.calls["n"] == 1  # the scan itself ran only once across both invocations
    assert second["run_id"] != first["run_id"]  # every invocation still gets its own durable run_id
    assert second["run_status"] == "COMPLETE"
    assert second["research_observations_inserted"] == 0  # nothing new inserted the second time
    # Not re-derived on the skip path — reused from the prior run, never fabricated as 0.
    assert second["successfully_scored"] is None
    assert second["unscorable"] is None


def test_run_daily_auto_scan_persists_durable_run_record(monkeypatch):
    monkeypatch.setattr(auto_scan, "TICKER_GROUPS", _STUB_UNIVERSES)
    monkeypatch.setattr(auto_scan, "check_data_health", lambda *a, **k: {
        **_HEALTHY, "resolvable_universes": ["E3 Universe A"],
    })
    fake_scan = _fake_execute_scan({"ZZE3SHARED.NS": True, "ZZE3A.NS": True})
    _patch_e2_and_maturation(monkeypatch, opened=1)

    summary = run_daily_auto_scan(trading_date=_date(8), universes=["E3 Universe A"], execute_scan_fn=fake_scan)
    run = fetch_auto_scan_run(summary["run_id"])

    assert run is not None
    assert run["trading_date"] == _date(8)
    assert run["status"] == "COMPLETE"
    assert run["unique_symbol_count"] == 2
    assert run["observations_inserted"] == 2
    assert run["signals_generated"] == 2
    assert run["configured_universes"] == ["E3 Universe A"]
    assert run["paper_opened"] == 1


# ── no-scoring-change guarantee (real main.execute_scan, boundary mocked) ──

def test_universe_membership_preserves_smallcap_liquidity_guard(monkeypatch):
    """A combined multi-universe run must not silently disable the
    Nifty-Smallcap-250-only liquidity guard for symbols that really belong
    to it — see stock_scanner/logic.py's `selected_universe ==
    "Nifty Smallcap 250"` check and main.py's `universe_membership` param."""
    seen = {}

    def _spy(ticker, hist, ticker_obj, portfolio_val, risk_pct, selected_universe=None, regime_data=None):
        seen[ticker] = selected_universe
        return {"Symbol": ticker, "Score": 70.0, "Quality_Gate_Pass": True, "Price": 100.0}

    monkeypatch.setattr("stock_scanner.pulse.get_current_regime", lambda: {
        "Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0,
    })
    monkeypatch.setattr(main_mod, "prefetch_metadata", lambda tickers: None)
    monkeypatch.setattr(main_mod, "get_stock_data", lambda *a, **k: pd.DataFrame({"Close": range(250)}))
    monkeypatch.setattr(main_mod, "apply_advanced_scoring", lambda df, config: df)
    monkeypatch.setattr(main_mod, "check_institutional_fortress", _spy)

    req = main_mod.ScanRequest(universe="AUTO_MULTI(Nifty Smallcap 250,Nifty 50)")
    main_mod.execute_scan(
        req,
        tickers_override=["ZZE3SMALL.NS", "ZZE3BIG.NS"],
        universe_membership={"ZZE3SMALL.NS": ["Nifty Smallcap 250"], "ZZE3BIG.NS": ["Nifty 50"]},
    )

    assert seen["ZZE3SMALL.NS"] == "Nifty Smallcap 250"
    assert seen["ZZE3BIG.NS"] == "AUTO_MULTI(Nifty Smallcap 250,Nifty 50)"


def test_no_broker_execution_path_in_auto_scan_module():
    for mod in (auto_scan, auto_scan_router):
        src = inspect.getsource(mod)
        for forbidden in ("generate_zerodha_url", "generate_dhan_url", "routers.brokers", "place_order"):
            assert forbidden not in src
