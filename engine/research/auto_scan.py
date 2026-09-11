"""
engine/research/auto_scan.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FORTRESS-E3 — Automated Multi-Universe EOD Scanning.

MARKET CLOSE -> VERIFY DATA HEALTH -> RESOLVE CONFIGURED UNIVERSES ->
BUILD UNIQUE SYMBOL UNION -> SCORE EACH SYMBOL ONCE -> RECORD UNIVERSE
MEMBERSHIP -> E1 RESEARCH OBSERVATIONS -> T1 QUALIFYING SIGNALS ->
E2 PAPER PORTFOLIO -> MATURE PREVIOUS E1 OUTCOMES.

Orchestrates existing engines (execute_scan, E1's prospective_store, E2's
policy_engine) unchanged. No scoring change. See
docs/research/AUTOMATED_MULTI_UNIVERSE_SCANNING.md.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fortress_config import TICKER_GROUPS
from utils.db import (
    create_auto_scan_run,
    fetch_latest_auto_scan_run,
    record_universe_memberships,
    update_auto_scan_run,
)

# Explicit, conservative default — NOT "every configured universe" — so an
# unset env var never silently scans the entire ticker database.
DEFAULT_AUTO_SCAN_UNIVERSES: Tuple[str, ...] = ("Nifty 50",)
_MIN_HISTORY_ROWS = 210  # same bar execute_scan's own circuit breaker uses


def resolve_configured_universes() -> List[str]:
    """FORTRESS_AUTO_SCAN_UNIVERSES: comma-separated universe names matching
    fortress_config.TICKER_GROUPS keys. Unset/empty -> DEFAULT_AUTO_SCAN_UNIVERSES."""
    raw = os.getenv("FORTRESS_AUTO_SCAN_UNIVERSES", "").strip()
    if not raw:
        return list(DEFAULT_AUTO_SCAN_UNIVERSES)
    return [name.strip() for name in raw.split(",") if name.strip()]


def build_symbol_union(universe_names: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    """Resolve membership of every (already-validated) configured universe,
    then union to unique symbols. Preserves the exact overlap-avoidance the
    story requires: RELIANCE in 4 universes still appears once in the
    returned union, with all 4 recorded in `membership`."""
    membership: Dict[str, List[str]] = {}
    for name in universe_names:
        for symbol in TICKER_GROUPS.get(name, []):
            membership.setdefault(symbol, [])
            if name not in membership[symbol]:
                membership[symbol].append(name)
    union = sorted(membership.keys())  # deterministic order for the scan loop
    return union, membership


def check_data_health(
    trading_date: str,
    configured_universes: List[str],
    get_ohlcv_fn: Optional[Callable[[str, str], Any]] = None,
) -> Dict[str, Any]:
    """Cheap pre-scan gate reusing existing signals rather than inventing a
    new health check: Bhav Copy freshness (utils.db.get_bhavcopy_fetch_status,
    only when Bhav Copy is the active OHLCV source), provider availability
    (market_data_provider.provider_status), expected universe resolution
    (which configured names actually exist in TICKER_GROUPS), and a canary
    OHLCV depth check against the first resolvable universe's first symbol
    (same >=210-row bar execute_scan's own circuit breaker enforces) so a
    systemic provider outage aborts before an expensive full scan rather
    than after burning through one via the breaker."""
    from utils.db import get_bhavcopy_fetch_status
    from utils.market_data_provider import provider_status

    if get_ohlcv_fn is None:
        from utils.market_data_provider import get_ohlcv as get_ohlcv_fn

    issues: List[str] = []
    resolvable = [u for u in configured_universes if u in TICKER_GROUPS]
    unresolved = [u for u in configured_universes if u not in TICKER_GROUPS]
    if not resolvable:
        issues.append("no_configured_universe_resolved")

    status = provider_status()
    bhav_status = None
    if status.get("ohlcv_source") == "bhavcopy":
        bhav_status = get_bhavcopy_fetch_status(trading_date)
        if bhav_status != "done":
            issues.append(f"bhavcopy_not_ready:{bhav_status or 'no_attempt_logged'}")

    canary_symbol = None
    canary_rows = 0
    if resolvable:
        canary_symbol = TICKER_GROUPS[resolvable[0]][0]
        try:
            hist = get_ohlcv_fn(canary_symbol, "1y")
            canary_rows = 0 if hist is None else len(hist)
        except Exception as e:
            issues.append(f"canary_fetch_failed:{e}")
        else:
            if hist is None or getattr(hist, "empty", True) or canary_rows < _MIN_HISTORY_ROWS:
                issues.append(f"insufficient_history_depth:{canary_rows}_rows_need_{_MIN_HISTORY_ROWS}")

    return {
        "healthy": not issues,
        "issues": issues,
        "provider_status": status,
        "bhavcopy_status": bhav_status,
        "canary_symbol": canary_symbol,
        "canary_rows": canary_rows,
        "resolvable_universes": resolvable,
        "unresolved_universes": unresolved,
    }


def _qualifying_count(scan_result: Any) -> int:
    records = scan_result.get("results") if isinstance(scan_result, dict) else scan_result
    return sum(1 for r in (records or []) if r.get("Quality_Gate_Pass"))


def run_daily_auto_scan(
    trading_date: Optional[str] = None,
    universes: Optional[List[str]] = None,
    get_ohlcv_fn: Optional[Callable[[str, str], Any]] = None,
    execute_scan_fn: Optional[Callable[..., Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The one idempotent 'paper-portfolio run'-equivalent daily command for
    evidence collection: DATA HEALTH -> MULTI-UNIVERSE SCAN -> E1 -> T1 ->
    E2 -> MATURATION -> summary. Safe to call more than once for the same
    trading_date: a prior COMPLETE run for that date is detected and the
    scan/E1/T1 steps are skipped entirely (never duplicated); E2 and
    maturation are already independently idempotent (FORTRESS-E2's
    signal_id-keyed decisions, E1's NOT_YET_MATURE-only updates) so they
    always re-run safely."""
    if get_ohlcv_fn is None:
        from utils.market_data_provider import get_ohlcv as get_ohlcv_fn
    if execute_scan_fn is None:
        from main import execute_scan as execute_scan_fn
    from main import ScanRequest

    trading_date = trading_date or datetime.now().strftime("%Y-%m-%d")
    configured = list(universes) if universes is not None else resolve_configured_universes()
    run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    create_auto_scan_run(run_id, trading_date, configured, started_at)

    summary: Dict[str, Any] = {
        "run_id": run_id, "trading_date": trading_date,
        "configured_universes": len(configured),
    }

    previous_complete = fetch_latest_auto_scan_run(trading_date=trading_date, status="COMPLETE")
    scan_failed_hard = False

    if previous_complete is not None:
        summary.update({
            "unique_symbols": previous_complete.get("unique_symbol_count"),
            "successfully_scored": None,
            "unscorable": None,
            "research_observations_inserted": 0,
            "signals_generated": previous_complete.get("signals_generated"),
            "circuit_breaker": "triggered" if previous_complete.get("circuit_breaker_tripped") else "not_triggered",
            "data_health": "healthy (scan already complete for this date — reused, not repeated)",
        })
        update_auto_scan_run(run_id, status="COMPLETE", scoring_version=previous_complete.get("scoring_version"))
    else:
        health = check_data_health(trading_date, configured, get_ohlcv_fn=get_ohlcv_fn)
        update_auto_scan_run(run_id, provider_health=health["provider_status"])

        if not health["healthy"]:
            scan_failed_hard = True
            reason = "; ".join(health["issues"])
            update_auto_scan_run(
                run_id, status="FAILED", completed_at=datetime.now(timezone.utc).isoformat(),
                reason=reason, unresolved_universes=health["unresolved_universes"],
            )
            summary.update({
                "unique_symbols": 0, "successfully_scored": 0, "unscorable": 0,
                "research_observations_inserted": 0, "signals_generated": 0,
                "circuit_breaker": "not_triggered", "data_health": "unhealthy",
                "reason": reason, "run_status": "FAILED",
            })
        else:
            resolved = health["resolvable_universes"]
            unresolved = health["unresolved_universes"]
            union_tickers, membership = build_symbol_union(resolved)
            update_auto_scan_run(
                run_id, resolved_universes=resolved, unresolved_universes=unresolved,
                unique_symbol_count=len(union_tickers),
            )

            membership_entries = [
                {"trading_date": trading_date, "symbol": sym, "universe": u, "run_id": run_id}
                for sym, universes_for_symbol in membership.items() for u in universes_for_symbol
            ]
            record_universe_memberships(membership_entries)
            update_auto_scan_run(run_id, membership_count=len(membership_entries))

            scan_label = f"AUTO_MULTI({','.join(resolved)})"
            req = ScanRequest(universe=scan_label)
            run_meta: Dict[str, Any] = {}
            scan_result = execute_scan_fn(
                req, tickers_override=union_tickers, run_meta=run_meta, universe_membership=membership,
            )

            tripped = bool(run_meta.get("circuit_breaker_tripped"))
            scanned = run_meta.get("scanned", 0) or 0
            failed = run_meta.get("failed", 0) or 0
            successfully_scored = max(scanned - failed, 0)
            obs_result = run_meta.get("research_observations_result") or {"inserted": 0, "duplicates": 0}
            signals_generated = _qualifying_count(scan_result)

            reason = None
            if tripped:
                reason = "circuit breaker tripped mid-scan — evidence for this run is incomplete/invalid"
            elif unresolved:
                reason = f"unresolved universes: {', '.join(unresolved)}"

            from stock_scanner.logic import FORTRESS_SCAN_LOGIC_VERSION

            from research.prospective_store import _git_sha

            update_auto_scan_run(
                run_id,
                scoring_version=FORTRESS_SCAN_LOGIC_VERSION,
                git_sha=_git_sha(),
                observations_inserted=obs_result.get("inserted", 0),
                signals_generated=signals_generated,
                circuit_breaker_tripped=tripped,
                reason=reason,
            )

            summary.update({
                "unique_symbols": len(union_tickers),
                "successfully_scored": successfully_scored,
                "unscorable": max(len(union_tickers) - successfully_scored, 0),
                "research_observations_inserted": obs_result.get("inserted", 0),
                "signals_generated": signals_generated,
                "circuit_breaker": "triggered" if tripped else "not_triggered",
                "data_health": "healthy",
                "unresolved_universes": unresolved,
            })
            scan_failed_hard = tripped

    # E2: position management always runs (freeing exposure/slots for open
    # positions is independent of today's scan quality); new entries are
    # only attempted from a healthy, untripped, freshly-scored run — a
    # failed/degraded scan or a skipped rerun never opens a position.
    from paper_trading.policy_engine import manage_open_positions, run_paper_portfolio
    if scan_failed_hard or previous_complete is not None:
        e2_result = manage_open_positions(get_ohlcv_fn=get_ohlcv_fn)
        e2_result["opened"] = 0
    else:
        e2_result = run_paper_portfolio(get_ohlcv_fn=get_ohlcv_fn)
    summary["paper_positions_opened"] = e2_result.get("opened", 0)
    summary["paper_positions_closed"] = e2_result.get("closed", e2_result.get("closed_today", 0))

    # Maturation of PRIOR observations always runs — independent of whether
    # today's scan happened at all.
    from research.prospective_store import mature_pending_outcomes
    maturation = mature_pending_outcomes(get_ohlcv_fn=get_ohlcv_fn)
    summary["outcomes_matured"] = maturation

    if summary.get("run_status"):
        final_status = summary["run_status"]
    elif scan_failed_hard:
        final_status = "FAILED"
    elif summary.get("unresolved_universes"):
        final_status = "DEGRADED"
    else:
        final_status = "COMPLETE"
    summary["run_status"] = final_status
    completed_at = datetime.now(timezone.utc).isoformat()
    update_auto_scan_run(
        run_id, status=final_status, completed_at=completed_at,
        paper_opened=summary["paper_positions_opened"], paper_closed=summary["paper_positions_closed"],
        summary_json=summary,
    )
    return summary


def _cli() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="FORTRESS-E3 automated multi-universe EOD scan")
    parser.add_argument("--trading-date", default=None)
    args = parser.parse_args()
    print(json.dumps(run_daily_auto_scan(trading_date=args.trading_date), indent=2, default=str))


if __name__ == "__main__":
    _cli()
