"""Bounded, idempotent Oracle outcome-ledger backfill."""
from __future__ import annotations

import argparse

from oracle_decision.service import build_decision
from oracle_outcomes.service import pending_rows
from utils.db import fetch_signal_ledger, upsert_oracle_outcomes


def run(limit: int = 100, dry_run: bool = False) -> dict:
    signals = fetch_signal_ledger(limit=limit)
    eligible, rows = 0, []
    for signal in signals:
        decision = build_decision(signal)
        if decision["decision"] == "UNAVAILABLE":
            continue
        eligible += 1
        rows.extend(pending_rows(signal, decision["decision"]))
    written = 0 if dry_run else upsert_oracle_outcomes(rows)
    return {"signals_inspected": len(signals), "eligible": eligible,
            "outcomes_to_create": len(rows), "writes": written, "dry_run": dry_run}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(run(limit=max(1, min(args.limit, 1000)), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
