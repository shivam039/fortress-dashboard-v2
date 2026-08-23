import pytest
from mf_lab.logic import compute_mf_conviction

def test_sub_score_sum_weights_to_100():
    fund = {
        "Sharpe": 1.5,
        "Sortino": 2.0,
        "Alpha": 5.0,
        "Volatility": 10.0,
        "Downside Deviation": 5.0,
        "3M Return": 3.0,
        "Expense Ratio": 0.5
    }
    peers = [fund, fund]
    res = compute_mf_conviction(fund, peers)
    assert 0 <= res["conviction_score"] <= 100
    assert 0 <= res["confidence_score"] <= 100

def test_single_fund_universe_no_zero_division():
    fund = {"Sharpe": 1.5}
    res = compute_mf_conviction(fund, [fund])
    assert "single_fund_universe" in res["risk_flags"]

def test_stale_nav_flag_triggered():
    fund = {"Sharpe": 1.5, "risk_flags": ["stale_data"]}
    res = compute_mf_conviction(fund, [fund])
    assert "stale_data" in res["risk_flags"]
    assert res["data_quality"] == "stale"

def test_backward_compat_fields_unchanged():
    from mf_lab.logic import enrich_mf_records_with_conviction
    records = [{"Scheme": "A", "Score": 50, "AI_Score": 60}]
    enriched = enrich_mf_records_with_conviction(records)
    assert enriched[0]["Score"] == 50
    assert enriched[0]["AI_Score"] == 60
    assert "conviction_score_v2" in enriched[0]
