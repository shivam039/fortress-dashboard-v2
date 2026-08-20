"""Regression tests converted from ad-hoc conviction score repro scripts."""

from __future__ import annotations

import pandas as pd

from engine.stock_scanner.logic import DEFAULT_SCORING_CONFIG, apply_advanced_scoring


def _base_stock(**overrides: object) -> dict[str, object]:
    stock: dict[str, object] = {
        "Symbol": "TEST",
        "Score": 50,
        "Price": 150.0,
        "RSI": 55.0,
        "News": "Neutral",
        "Events": "✅ Safe",
        "Sector": "IT",
        "Avg_Value_20D_Cr": 500.0,
        "Market_Cap_Cr": 800000.0,
        "Debt_To_Equity": 0.1,
        "Technical_Raw": 50.0,
        "Fundamental_Raw": 45.0,
        "Sentiment_Raw": 50.0,
        "Context_Raw": 50.0,
        "RS_Score": 2.0,
        "RS_Composite": 1.2,
        "Vol_Surge_Ratio": 1.5,
        "Dist_52W_High_Pct": 5.0,
        "Extension_Pct": 2.0,
        "Is_Coiling": False,
        "Black_Swan_Flag": 0,
        "Regime_Multiplier": 1.0,
    }
    stock.update(overrides)
    return stock


def test_positive_conviction_survives_advanced_scoring() -> None:
    df = pd.DataFrame(
        [
            _base_stock(
                Symbol="INFY",
                Score=65,
                Price=1800.0,
                Technical_Raw=45.0,
                Fundamental_Raw=50.0,
                Context_Raw=40.0,
                RS_Composite=1.1,
                Vol_Surge_Ratio=1.2,
                Extension_Pct=3.0,
            )
        ]
    )

    scored = apply_advanced_scoring(df, DEFAULT_SCORING_CONFIG)

    assert scored.loc[0, "Score"] > 0
    assert scored.loc[0, "Quality_Gate_Pass"]
    assert scored.loc[0, "Verdict"] != "❌ FAIL"


def test_zero_and_positive_conviction_are_differentiated() -> None:
    df = pd.DataFrame(
        [
            _base_stock(
                Symbol="STOCK1",
                Score=0,
                Technical_Raw=0.0,
                Fundamental_Raw=30.0,
                Context_Raw=30.0,
                RS_Score=0.0,
                RS_Composite=0.9,
                Vol_Surge_Ratio=1.0,
                Dist_52W_High_Pct=20.0,
                Extension_Pct=0.0,
            ),
            _base_stock(Symbol="STOCK2"),
        ]
    )

    scored = apply_advanced_scoring(df, DEFAULT_SCORING_CONFIG)
    scores = scored.set_index("Symbol")["Score"]

    assert scores["STOCK2"] > scores["STOCK1"]
    assert scores["STOCK2"] > 0


def test_identical_raw_scores_do_not_collapse_to_zero() -> None:
    df = pd.DataFrame(
        [
            _base_stock(
                Symbol="STOCK1",
                Score=30,
                Technical_Raw=10.0,
                Fundamental_Raw=30.0,
                Context_Raw=20.0,
                RS_Score=0.0,
                RS_Composite=0.9,
                Vol_Surge_Ratio=1.0,
                Dist_52W_High_Pct=20.0,
                Extension_Pct=0.0,
            ),
            _base_stock(
                Symbol="STOCK2",
                Score=30,
                Price=100.0,
                Sector="Finance",
                Technical_Raw=10.0,
                Fundamental_Raw=30.0,
                Context_Raw=20.0,
                RS_Score=0.0,
                RS_Composite=0.9,
                Vol_Surge_Ratio=1.0,
                Dist_52W_High_Pct=20.0,
                Extension_Pct=0.0,
            ),
        ]
    )

    scored = apply_advanced_scoring(df, DEFAULT_SCORING_CONFIG)

    assert (scored["Score"] > 0).all()
    assert scored["Score"].notna().all()


def test_uptrend_and_downtrend_scores_remain_nonzero_and_ordered() -> None:
    df = pd.DataFrame(
        [
            _base_stock(
                Symbol="UPTREND",
                Score=70,
                Price=2000.0,
                Technical_Raw=60.0,
                Fundamental_Raw=50.0,
                Context_Raw=50.0,
                RS_Score=3.0,
                RS_Composite=1.3,
                Vol_Surge_Ratio=1.8,
                Extension_Pct=5.0,
            ),
            _base_stock(
                Symbol="DOWNTREND",
                Score=10,
                Price=500.0,
                Sector="Finance",
                Avg_Value_20D_Cr=200.0,
                Market_Cap_Cr=300000.0,
                Debt_To_Equity=0.5,
                Technical_Raw=5.0,
                Fundamental_Raw=20.0,
                Context_Raw=15.0,
                RS_Score=-2.0,
                RS_Composite=0.8,
                Vol_Surge_Ratio=0.9,
                Dist_52W_High_Pct=40.0,
                Extension_Pct=-10.0,
            ),
        ]
    )

    scored = apply_advanced_scoring(df, DEFAULT_SCORING_CONFIG)
    scores = scored.set_index("Symbol")["Score"]

    assert scores["UPTREND"] > scores["DOWNTREND"]
    assert (scores > 0).all()
