from utils.db import fetch_oracle_outcomes, upsert_oracle_outcomes


def row(horizon=1):
    return {
        "signal_id": 99001, "oracle_version": "oracle-v1", "decision": "POSITIVE",
        "symbol": "TEST.NS", "decision_at": "2026-01-02", "horizon": horizon,
        "reference_price": 100, "future_price": None, "return_pct": None,
        "outcome_as_of": None, "status": "PENDING",
    }


def test_outcome_identity_is_idempotent_and_maturation_updates_only_outcome_fields():
    assert upsert_oracle_outcomes([row()]) == 1
    assert upsert_oracle_outcomes([{**row(), "status": "MATURED", "future_price": 101, "return_pct": 1.0}]) == 1
    rows = fetch_oracle_outcomes(signal_id=99001)
    assert len(rows) == 1
    assert rows[0]["decision"] == "POSITIVE"
    assert rows[0]["reference_price"] == 100
    assert rows[0]["status"] == "MATURED"
