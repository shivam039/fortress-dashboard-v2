from datetime import datetime, timedelta, timezone

from oracle_decision.service import build_decision


def signal(**overrides):
    value = {
        "id": 1,
        "symbol": "TEST.NS",
        "score": 74,
        "generated_at": "2026-09-12T10:00:00+00:00",
        "data_timestamp": "2026-09-12T10:00:00+00:00",
        "feature_snapshot": {"Verdict": "🚀 PASS", "Strategy": "Momentum Pick"},
    }
    value.update(overrides)
    return value


def test_positive_is_deterministic_and_explainable():
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    first = build_decision(signal(), now)
    assert first == build_decision(signal(), now)
    assert first["decision"] == "POSITIVE"
    assert first["reasons"][0]["key"] == "score"


def test_watch_is_neutral_and_avoid_is_negative():
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    assert build_decision(signal(feature_snapshot={"Verdict": "🟡 WATCH"}), now)["decision"] == "NEUTRAL"
    assert build_decision(signal(feature_snapshot={"Verdict": "🚨 AVOID"}), now)["decision"] == "NEGATIVE"


def test_missing_and_stale_evidence_are_unavailable():
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    assert build_decision(signal(score=None), now)["decision"] == "UNAVAILABLE"
    old = (now - timedelta(days=2)).isoformat()
    assert build_decision(signal(data_timestamp=old), now)["decision"] == "UNAVAILABLE"


def test_unknown_semantics_do_not_guess():
    result = build_decision(signal(feature_snapshot={"Verdict": "UNKNOWN"}), datetime(2026, 9, 12, 12, tzinfo=timezone.utc))
    assert result["decision"] == "UNAVAILABLE"
