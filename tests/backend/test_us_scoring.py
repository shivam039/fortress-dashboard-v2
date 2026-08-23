import pytest
from us_investing.logic import _score_universe

def test_score_range():
    records = [
        {
            "symbol": "AAPL",
            "price": 150,
            "returns_1y": 20.0,
            "returns_1m": 5.0,
            "returns_3m": 10.0,
            "volatility_30d": 15.0,
            "max_drawdown_1y": -10.0,
            "pe_ratio": 25.0,
            "avg_volume": 50000000
        }
    ]
    scored = _score_universe(records)
    for r in scored:
        assert 0 <= r["conviction_score"] <= 100
        assert 0 <= r["confidence_score"] <= 100

def test_inr_conversion_present():
    records = [
        {
            "symbol": "AAPL",
            "price": 150,
            "price_inr": 12600.0,
            "returns_1y": 20.0,
        }
    ]
    scored = _score_universe(records)
    assert scored[0]["price_inr"] == 12600.0

def test_single_symbol_no_crash():
    records = [
        {
            "symbol": "AAPL",
            "price": 150,
            "pe_ratio": 25.0
        }
    ]
    scored = _score_universe(records)
    assert scored[0]["conviction_score"] is not None
