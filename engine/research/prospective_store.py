"""
engine/research/prospective_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FORTRESS-E1 — Prospective Evidence Collection.

REAL SCAN -> research_observations (append-only, one per successfully
scored ticker) -> research_outcomes (5D/10D/20D/60D, mature only when real
future sessions exist) -> R1-compatible export -> R2 (existing, unchanged).

No scoring change. No fabricated/backdated data. See
docs/research/PROSPECTIVE_EVIDENCE_COLLECTION.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utils.db import (
    fetch_pending_research_outcomes,
    fetch_research_observations,
    fetch_research_outcomes,
    finalize_research_outcome,
    record_research_observations,
)

SCHEMA_VERSION = "e1-v1"
_OBS_NAMESPACE = uuid.UUID("6f6e6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f")
MIN_STATUS_SAMPLE_SIZE = 20  # matches score-evidence.ts's MIN_EVIDENCE_SAMPLE_SIZE
SAMPLE_MILESTONES = (100, 250, 500, 1000, 2500, 5000)


def _git_sha() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def observation_id_for(trading_date: str, symbol: str, scoring_version: str) -> str:
    """Deterministic id from the natural idempotency key — the same
    (trading_date, symbol, scoring_version) always yields the same id,
    independent of the DB's own auto-increment counter."""
    return str(uuid.uuid5(_OBS_NAMESPACE, f"{trading_date}|{symbol}|{scoring_version}"))


def build_observation_entries(
    scored_rows: List[Dict[str, Any]],
    scan_id: Optional[int],
    trading_date: str,
    scoring_version: str,
    data_source: Optional[str] = None,
    git_sha: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert scored scan rows (apply_advanced_scoring's output shape —
    same fields R1's historical_dataset.py already reads from raw_data,
    reused here rather than inventing a second field mapping) into
    record_research_observations() entries. Pure function — no DB access —
    for easy testing."""
    now_iso = datetime.now(timezone.utc).isoformat()
    git_sha = git_sha if git_sha is not None else _git_sha()
    entries = []
    for row in scored_rows:
        symbol = row.get("Symbol")
        if not symbol:
            continue
        entries.append({
            "observation_id": observation_id_for(trading_date, symbol, scoring_version),
            "scan_id": scan_id,
            "symbol": symbol,
            "exchange": "NSE",
            "trading_date": trading_date,
            "observation_timestamp": now_iso,
            "fortress_score": row.get("Score"),
            "component_scores": {
                "technical": row.get("Technical_Score"),
                "fundamental": row.get("Fundamental_Score"),
                "sentiment": row.get("Sentiment_Score"),
                "context": row.get("Context_Score"),
            },
            "market_regime": row.get("Market_Regime") or row.get("Regime"),
            "sector": row.get("Sector"),
            "features_json": {
                k: row[k] for k in (
                    "RSI", "RS_6M", "RS_Composite", "RS_Rank", "RS_Score",
                    "Avg_Value_20D_Cr", "Market_Cap_Cr", "Debt_To_Equity",
                    "Vol_Surge_Ratio", "Dist_52W_High_Pct",
                ) if k in row
            },
            "quality_gate_pass": bool(row.get("Quality_Gate_Pass")),
            "quality_gate_failures": row.get("Quality_Gate_Failures") or "",
            "data_source": data_source,
            "data_timestamp": row.get("Data_As_Of"),
            "reference_price": row.get("Price"),
            "scoring_version": scoring_version,
            "schema_version": SCHEMA_VERSION,
            "git_sha": git_sha,
            "passed_criteria": bool(row.get("Quality_Gate_Pass")),
        })
    return entries


def collect_from_scan(
    scored_rows: List[Dict[str, Any]],
    scan_id: Optional[int],
    trading_date: str,
    scoring_version: str,
    data_source: Optional[str] = None,
) -> Dict[str, int]:
    """The one call site engine/main.py's scan-completion path needs.
    scored_rows must be the FULL successfully-scored universe for this
    scan (score_df), not a recommendations-only subset — see
    docs/research/PROSPECTIVE_EVIDENCE_COLLECTION.md `1. EVIDENCE UNIVERSE`.
    """
    entries = build_observation_entries(scored_rows, scan_id, trading_date, scoring_version, data_source)
    return record_research_observations(entries)


def mature_pending_outcomes(get_ohlcv_fn: Optional[Callable[[str, str], Any]] = None) -> Dict[str, int]:
    """Advance every NOT_YET_MATURE outcome as far as real price data
    allows. Reuses R1/R2's own return definition —
    unadjusted_close(T+h)/unadjusted_close(T) - 1 — via the same trading
    sessions the fetched OHLCV series actually contains (no invented
    calendar). Safe to rerun: finalize_research_outcome only ever updates a
    row still in NOT_YET_MATURE."""
    # Local import: callers/tests can inject their own price function
    # without this module ever requiring market_data_provider at load time.
    if get_ohlcv_fn is None:
        from utils.market_data_provider import get_ohlcv as get_ohlcv_fn

    pending = fetch_pending_research_outcomes()
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for row in pending:
        by_symbol.setdefault(row["symbol"], []).append(row)

    matured = 0
    unavailable = 0
    for symbol, rows in by_symbol.items():
        try:
            hist = get_ohlcv_fn(symbol, "1y")
        except Exception:
            continue  # provider hiccup — leave NOT_YET_MATURE, retry next run
        if hist is None or getattr(hist, "empty", True):
            continue

        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in hist.index]
        date_idx = {d: i for i, d in enumerate(dates)}
        closes = hist["Close"] if "Close" in getattr(hist, "columns", []) else None

        for row in rows:
            base_date = row["trading_date"]
            if base_date not in date_idx:
                continue  # T0 not (yet) in this series — try again later
            target_i = date_idx[base_date] + row["horizon"]
            if closes is None or target_i >= len(dates):
                continue  # NOT_YET_MATURE: not enough future sessions exist yet
            target_date = dates[target_i]
            close = closes.iloc[target_i]
            base_price = row.get("reference_price")

            if close is None or (isinstance(close, float) and math.isnan(close)) or float(close) <= 0:
                finalize_research_outcome(
                    row["id"], "MISSING_DATA", target_trading_date=target_date,
                    failure_reason="missing_or_invalid_future_close",
                )
                unavailable += 1
                continue
            if not base_price or float(base_price) <= 0:
                finalize_research_outcome(
                    row["id"], "MISSING_DATA", target_trading_date=target_date,
                    failure_reason="missing_reference_price",
                )
                unavailable += 1
                continue

            forward_return = float(close) / float(base_price) - 1.0
            finalize_research_outcome(
                row["id"], "MATURED", target_trading_date=target_date,
                future_price=float(close), price_source="market_data_provider",
                price_timestamp=target_date, forward_return=forward_return,
            )
            matured += 1

    return {"checked": len(pending), "matured": matured, "unavailable": unavailable}


def _bucket(score: Optional[float]) -> str:
    from research.forward_return_validation import _assign_bucket
    return _assign_bucket(score)


def get_status() -> Dict[str, Any]:
    """Lightweight R2-readiness status: matured N by score bucket x
    horizon, milestone progress. Never presents a tiny sample as if it
    were sufficient evidence."""
    observations = fetch_research_observations()
    outcomes = fetch_research_outcomes(status="MATURED")
    obs_by_id = {o["observation_id"]: o for o in observations}

    total = len(observations)
    milestone = max((m for m in SAMPLE_MILESTONES if total >= m), default=0)
    next_milestone = next((m for m in SAMPLE_MILESTONES if total < m), None)

    bucket_counts: Dict[str, int] = {}
    cells: Dict[str, Dict[str, Any]] = {}
    for outcome in outcomes:
        obs = obs_by_id.get(outcome["observation_id"])
        if obs is None:
            continue
        bucket = _bucket(obs.get("fortress_score"))
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        key = f"{bucket}|{outcome['horizon']}D"
        cells.setdefault(key, {"bucket": bucket, "horizon": outcome["horizon"], "n": 0})
        cells[key]["n"] += 1

    for cell in cells.values():
        cell["status"] = "SUFFICIENT_SAMPLE" if cell["n"] >= MIN_STATUS_SAMPLE_SIZE else "INSUFFICIENT_SAMPLE"

    return {
        "total_observations": total,
        "matured_outcomes": len(outcomes),
        "milestone_reached": milestone,
        "next_milestone": next_milestone,
        "score_bucket_distribution": bucket_counts,
        "bucket_horizon_readiness": sorted(cells.values(), key=lambda c: (c["bucket"], c["horizon"])),
    }


def export_r1(output_path: str) -> Dict[str, Any]:
    """Deterministic export of the prospective store into the same
    observations/labels/sessions/prices tables engine/research/
    forward_return_validation.py already reads — this is what makes it
    'R1-compatible' rather than a parallel research system. `runs` is
    intentionally omitted: prospective rows have no bundle-selection
    concept to record there, and R2's own query never touches it."""
    out = Path(output_path)
    if out.exists():
        raise FileExistsError(f"{output_path} already exists — export to a new path")

    observations = fetch_research_observations()
    outcomes = fetch_research_outcomes()
    obs_by_id = {o["observation_id"]: o for o in observations}

    conn = sqlite3.connect(str(out))
    try:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE sessions (date TEXT PRIMARY KEY)")
        conn.execute("""CREATE TABLE observations (
            date TEXT, symbol TEXT, fortress_score REAL, technical_score REAL,
            fundamental_score REAL, sentiment_score REAL, context_score REAL,
            market_regime TEXT, sector TEXT, quality_gate_pass INTEGER,
            quality_gate_failures TEXT, features_json TEXT,
            PRIMARY KEY (date, symbol))""")
        conn.execute("""CREATE TABLE labels (
            date TEXT, symbol TEXT, horizon INTEGER, target_date TEXT,
            forward_return REAL, status TEXT,
            PRIMARY KEY (date, symbol, horizon))""")
        conn.execute("CREATE TABLE prices (date TEXT, symbol TEXT, close REAL, PRIMARY KEY (date, symbol))")

        sessions = set()
        scoring_versions = set()
        for o in observations:
            comp = o.get("component_scores") or {}
            conn.execute(
                "INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (o["trading_date"], o["symbol"], o.get("fortress_score"),
                 comp.get("technical"), comp.get("fundamental"), comp.get("sentiment"), comp.get("context"),
                 o.get("market_regime"), o.get("sector"),
                 1 if o.get("quality_gate_pass") else 0, o.get("quality_gate_failures"),
                 json.dumps(o.get("features_json") or {})),
            )
            if o.get("reference_price") is not None:
                conn.execute("INSERT OR IGNORE INTO prices VALUES (?,?,?)",
                             (o["trading_date"], o["symbol"], o["reference_price"]))
            sessions.add(o["trading_date"])
            scoring_versions.add(o.get("scoring_version"))

        for outcome in outcomes:
            obs = obs_by_id.get(outcome["observation_id"])
            if obs is None:
                continue
            matured = outcome["status"] == "MATURED"
            conn.execute(
                "INSERT OR IGNORE INTO labels VALUES (?,?,?,?,?,?)",
                (obs["trading_date"], obs["symbol"], outcome["horizon"],
                 outcome.get("target_trading_date"),
                 outcome.get("forward_return") if matured else None,
                 "ok" if matured else outcome["status"].lower()),
            )
            if matured and outcome.get("future_price") is not None and outcome.get("target_trading_date"):
                conn.execute("INSERT OR IGNORE INTO prices VALUES (?,?,?)",
                             (outcome["target_trading_date"], obs["symbol"], outcome["future_price"]))
                sessions.add(outcome["target_trading_date"])

        for s in sorted(sessions):
            conn.execute("INSERT OR IGNORE INTO sessions VALUES (?)", (s,))

        generated_at = datetime.now(timezone.utc).isoformat()
        meta = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "scoring_versions": ",".join(sorted(v for v in scoring_versions if v)),
            "observation_count": str(len(observations)),
            "source": "prospective_store (FORTRESS-E1)",
        }
        conn.executemany("INSERT INTO metadata VALUES (?,?)", list(meta.items()))
        conn.commit()
    finally:
        conn.close()

    return {"path": str(out), "observation_count": len(observations), "generated_at": generated_at}


def _cli() -> None:
    parser = argparse.ArgumentParser(description="FORTRESS-E1 prospective evidence collection")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("mature")
    exp = sub.add_parser("export")
    exp.add_argument("--output", required=True)
    val = sub.add_parser("validate")
    val.add_argument("--output", required=True)
    val.add_argument("--benchmark", default=None)
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(get_status(), indent=2))
    elif args.command == "mature":
        print(json.dumps(mature_pending_outcomes(), indent=2))
    elif args.command == "export":
        print(json.dumps(export_r1(args.output), indent=2))
    elif args.command == "validate":
        status = get_status()
        eligible = [c for c in status["bucket_horizon_readiness"] if c["status"] == "SUFFICIENT_SAMPLE"]
        result = export_r1(args.output)
        if not eligible:
            print(json.dumps({**result, "r2_ran": False,
                               "reason": "no bucket/horizon cell has >= "
                                         f"{MIN_STATUS_SAMPLE_SIZE} matured observations yet"}, indent=2))
            return
        from research.forward_return_validation import run_forward_return_validation
        report = run_forward_return_validation(args.output, benchmark_symbol=args.benchmark)
        print(json.dumps({**result, "r2_ran": True, "r2_summary": report.summary_findings}, indent=2))


if __name__ == "__main__":
    _cli()
