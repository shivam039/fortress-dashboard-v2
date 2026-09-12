from oracle_outcomes.service import evaluate_outcomes, scorecard


def signal():
    return {"id": 7, "symbol": "TEST.NS", "generated_at": "2026-01-02", "price_used": 100, "oracle_decision": "POSITIVE", "feature_snapshot": {"Price": 100}}


def test_trading_day_horizons_ignore_pre_decision_and_calendar_days():
    bars = [{"date": "2026-01-01", "close": 999}, {"date": "2026-01-05", "close": 101}, {"date": "2026-01-06", "close": 102}]
    outcomes = evaluate_outcomes(signal(), bars, horizons=(1, 2))
    assert outcomes[0]["status"] == "MATURED" and outcomes[0]["future_price"] == 101
    assert outcomes[1]["future_price"] == 102


def test_pending_and_missing_reference_are_explicit():
    assert evaluate_outcomes(signal(), [{"date": "2026-01-05", "close": 101}], horizons=(5,))[0]["status"] == "PENDING"
    broken = {**signal(), "price_used": None, "feature_snapshot": {}}
    assert evaluate_outcomes(broken, [], horizons=(1,))[0]["status"] == "DATA_UNAVAILABLE"


def test_scorecard_reports_samples_and_exclusions_without_accuracy_claims():
    rows = evaluate_outcomes(signal(), [{"date": "2026-01-05", "close": 110}], horizons=(1,))
    rows.append({**rows[0], "status": "PENDING", "return_pct": None})
    card = scorecard(rows, min_sample=2)[0]
    assert card["sample_count"] == 1
    assert card["exclusion_count"] == 1
    assert card["status"] == "INSUFFICIENT_SAMPLE"
