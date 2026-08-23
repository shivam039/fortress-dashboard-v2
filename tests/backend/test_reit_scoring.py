import pytest
from reit_invits.logic import _score_universe

def test_score_range():
    records = [
        {
            "symbol": "TEST1",
            "price": 100,
            "yield_pct": 8.0,
            "returns_1y": 15.0,
            "returns_1m": 2.0,
            "volatility_30d": 12.0,
            "max_drawdown_1y": -5.0,
            "returns_3m": 5.0,
        },
        {
            "symbol": "TEST2",
            "price": 50,
            "yield_pct": 5.0,
            "returns_1y": 5.0,
            "returns_1m": -1.0,
            "volatility_30d": 20.0,
            "max_drawdown_1y": -15.0,
            "returns_3m": 1.0,
        }
    ]
    scored = _score_universe(records)
    for r in scored:
        assert 0 <= r["conviction_score"] <= 100
        assert 0 <= r["confidence_score"] <= 100

def test_confidence_degrades_with_missing_data():
    records = [
        {
            "symbol": "TEST1",
            "price": 100,
            "yield_pct": 8.0,
            "returns_1y": None,
            "returns_1m": None,
            "volatility_30d": None,
            "max_drawdown_1y": None,
            "returns_3m": None,
        }
    ]
    scored = _score_universe(records)
    assert scored[0]["confidence_score"] < 50

def test_stale_data_flag():
    records = [
        {
            "symbol": "TEST1",
            "price": 100,
            "data_quality": "stale"
        }
    ]
    scored = _score_universe(records)
    assert scored[0]["confidence_score"] < 100
