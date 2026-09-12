"""Interpret one immutable Fortress signal without changing its scoring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


STALE_AFTER = timedelta(days=1)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _item(key: str, label: str, value: Any) -> Dict[str, Any]:
    return {"key": key, "label": label, "value": value}


def build_decision(signal: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return the approved Oracle contract for one signal-ledger snapshot."""
    now = now or datetime.now(timezone.utc)
    if not signal.get("id") or not signal.get("symbol"):
        return _unavailable(signal, "missing_signal_identity")
    if signal.get("score") is None:
        return _unavailable(signal, "missing_score")

    generated = _parse_timestamp(signal.get("generated_at"))
    data_as_of = _parse_timestamp(signal.get("data_timestamp")) or generated
    if generated is None or data_as_of is None:
        return _unavailable(signal, "missing_freshness_timestamp")
    if now - data_as_of > STALE_AFTER:
        return _unavailable(signal, "stale_data", data_as_of)

    snapshot = signal.get("feature_snapshot") or {}
    verdict = str(snapshot.get("Verdict") or signal.get("risk_classification") or "").upper()
    if "FAIL" in verdict or "AVOID" in verdict:
        decision = "NEGATIVE"
    elif "HIGH" in verdict or "PASS" in verdict:
        decision = "POSITIVE"
    elif "WATCH" in verdict:
        decision = "NEUTRAL"
    else:
        return _unavailable(signal, "unsupported_scanner_semantics", data_as_of)

    reasons: List[Dict[str, Any]] = [_item("score", "Fortress score", signal["score"])]
    cautions: List[Dict[str, Any]] = []
    for key, label in (("Strategy", "Strategy"), ("Market_Regime", "Market regime"), ("RS_Score", "Relative strength")):
        if snapshot.get(key) is not None:
            reasons.append(_item(key, label, snapshot[key]))
    failures = snapshot.get("Quality_Gate_Failures") or signal.get("risk_classification")
    if failures and ("FAIL" in str(failures).upper() or "AVOID" in str(failures).upper()):
        cautions.append(_item("risk_classification", "Risk classification", failures))
    if snapshot.get("Black_Swan_Flag"):
        cautions.append(_item("Black_Swan_Flag", "Black swan flag", snapshot["Black_Swan_Flag"]))

    return {
        "signal_id": signal["id"],
        "symbol": signal["symbol"],
        "decision": decision,
        "confidence": "MEDIUM" if cautions else "HIGH",
        "score": signal["score"],
        "reasons": reasons,
        "cautions": cautions,
        "data_as_of": data_as_of.isoformat(),
        "generated_at": generated.isoformat(),
        "source_context": {
            "scan_id": signal.get("scan_id"),
            "scan_version": signal.get("scan_version"),
            "universe": signal.get("universe"),
            "data_source": signal.get("data_source"),
        },
        "paper_trade": {"available": True, "signal_id": signal["id"]},
    }


def _unavailable(signal: Dict[str, Any], reason: str, data_as_of: Optional[datetime] = None) -> Dict[str, Any]:
    return {
        "signal_id": signal.get("id"),
        "symbol": signal.get("symbol"),
        "decision": "UNAVAILABLE",
        "confidence": "LOW",
        "score": signal.get("score"),
        "reasons": [],
        "cautions": [_item("unavailable_reason", "Decision unavailable", reason)],
        "data_as_of": data_as_of.isoformat() if data_as_of else signal.get("data_timestamp"),
        "generated_at": signal.get("generated_at"),
        "source_context": {"scan_id": signal.get("scan_id"), "scan_version": signal.get("scan_version"), "universe": signal.get("universe"), "data_source": signal.get("data_source")},
        "paper_trade": {"available": False, "signal_id": signal.get("id")},
    }
