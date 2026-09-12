"""Pure outcome and descriptive scorecard calculations."""
from __future__ import annotations

from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional

ORACLE_VERSION = "oracle-v1"
HORIZONS = (1, 5, 20)
MAX_MATURATION_BATCH = 200


def evaluate_outcomes(signal: Dict[str, Any], bars: Iterable[Dict[str, Any]], horizons=HORIZONS) -> List[Dict[str, Any]]:
    """Evaluate only bars after the immutable decision timestamp."""
    snapshot = signal.get("feature_snapshot") or {}
    reference = signal.get("price_used") or snapshot.get("Price")
    try:
        reference = float(reference)
    except (TypeError, ValueError):
        reference = 0.0
    decision_at = str(signal.get("generated_at") or "")[:10]
    future = [bar for bar in bars if str(bar.get("date", ""))[:10] > decision_at]
    results = []
    for horizon in horizons:
        base = {
            "signal_id": signal.get("id"), "symbol": signal.get("symbol"),
            "oracle_version": ORACLE_VERSION, "decision": signal.get("oracle_decision"),
            "decision_at": signal.get("generated_at"), "horizon": horizon,
            "reference_price": reference or None,
        }
        if reference <= 0:
            results.append({**base, "future_price": None, "return_pct": None, "status": "DATA_UNAVAILABLE"})
        elif len(future) < horizon:
            results.append({**base, "future_price": None, "return_pct": None, "status": "PENDING"})
        else:
            future_price = future[horizon - 1].get("close")
            try:
                future_price = float(future_price)
                result = round((future_price / reference - 1) * 100, 4)
            except (TypeError, ValueError, ZeroDivisionError):
                future_price, result = None, None
            results.append({**base, "future_price": future_price, "return_pct": result,
                            "outcome_as_of": future[horizon - 1].get("date"),
                            "status": "MATURED" if result is not None else "DATA_UNAVAILABLE"})
    return results


def scorecard(outcomes: Iterable[Dict[str, Any]], min_sample: int = 20) -> List[Dict[str, Any]]:
    groups: Dict[tuple, List[float]] = {}
    exclusions: Dict[tuple, int] = {}
    for outcome in outcomes:
        key = (outcome.get("decision"), outcome.get("horizon"))
        if outcome.get("status") != "MATURED" or outcome.get("return_pct") is None:
            exclusions[key] = exclusions.get(key, 0) + 1
            continue
        groups.setdefault(key, []).append(float(outcome["return_pct"]))
    keys = set(groups) | set(exclusions)
    return [{
        "decision": decision, "horizon": horizon, "sample_count": len(groups.get((decision, horizon), [])),
        "mean_return_pct": round(mean(groups[(decision, horizon)]), 4) if groups.get((decision, horizon)) else None,
        "median_return_pct": round(median(groups[(decision, horizon)]), 4) if groups.get((decision, horizon)) else None,
        "positive_return_rate_pct": round(sum(v > 0 for v in groups.get((decision, horizon), [])) / len(groups[(decision, horizon)]) * 100, 2) if groups.get((decision, horizon)) else None,
        "exclusion_count": exclusions.get((decision, horizon), 0),
        "status": "INSUFFICIENT_SAMPLE" if len(groups.get((decision, horizon), [])) < min_sample else "OBSERVED",
    } for decision, horizon in sorted(keys, key=str)]


def pending_rows(signal: Dict[str, Any], decision: str) -> List[Dict[str, Any]]:
    """Create the three idempotent ledger identities for one eligible signal."""
    reference = signal.get("price_used") or (signal.get("feature_snapshot") or {}).get("Price")
    try:
        reference = float(reference)
    except (TypeError, ValueError):
        reference = None
    return [{
        "signal_id": signal["id"], "oracle_version": ORACLE_VERSION,
        "decision": decision, "symbol": signal["symbol"],
        "decision_at": signal.get("generated_at"), "horizon": horizon,
        "reference_price": reference, "future_price": None, "return_pct": None,
        "outcome_as_of": None,
        "status": "PENDING" if reference and reference > 0 else "DATA_UNAVAILABLE",
    } for horizon in HORIZONS]


def mature_pending(limit: int = 200) -> Dict[str, int]:
    """Mature a bounded batch of persisted Oracle outcomes."""
    from utils.db import fetch_oracle_outcomes, fetch_signal_ledger, upsert_oracle_outcomes
    from utils.market_data_provider import get_ohlcv

    bounded = max(1, min(int(limit), MAX_MATURATION_BATCH))
    pending = fetch_oracle_outcomes(status="PENDING")[:bounded]
    matured, unavailable = 0, 0
    updates = []
    for outcome in pending:
        signals = fetch_signal_ledger(signal_id=outcome["signal_id"], limit=1)
        if not signals:
            unavailable += 1
            continue
        history = get_ohlcv(outcome["symbol"], "1y")
        bars = [] if history is None else [
            {"date": timestamp.strftime("%Y-%m-%d"), "close": row.get("Close")}
            for timestamp, row in history.iterrows()
        ]
        signal = {**signals[0], "oracle_decision": outcome["decision"]}
        evaluated = evaluate_outcomes(signal, bars, horizons=(outcome["horizon"],))[0]
        if evaluated["status"] == "PENDING":
            continue
        updates.append({**outcome, **evaluated})
        if evaluated["status"] == "MATURED":
            matured += 1
        else:
            unavailable += 1
    if updates:
        upsert_oracle_outcomes(updates)
    return {"checked": len(pending), "matured": matured, "unavailable": unavailable,
            "updated": len(updates), "limit": bounded}
