from datetime import datetime, timedelta

import pandas as pd
from stock_scanner.ui_helpers import prepare_screener_table
from streamlit.testing.v1 import AppTest

from stock_scanner import logic
from stock_scanner.logic import (
    _apply_quality_gates,
    _resolve_conviction_score,
    apply_advanced_scoring,
)


def test_resolve_conviction_score_uses_fallback_only_when_needed():
    assert _resolve_conviction_score(0, 42.7, -20) == 22.7
    assert _resolve_conviction_score(35, 90, -20) == 35
    assert _resolve_conviction_score(-5, 18.2, 0) == 18.2


def test_quality_gate_fail_forces_score_to_zero():
    df = pd.DataFrame(
        [
            {
                "Symbol": "TEST",
                "Score": 0,
                "Price": 75.0,
                "Avg_Value_20D_Cr": 12.0,
                "Market_Cap_Cr": 5000.0,
                "Debt_To_Equity": 0.5,
                "Technical_Raw": 10.0,
                "Fundamental_Raw": 10.0,
                "Sentiment_Raw": 10.0,
                "Context_Raw": 10.0,
                "RSI": 50.0,
                "RS_Score": 0.0,
                "RS_Composite": 1.0,
                "Vol_Surge_Ratio": 1.0,
                "Dist_52W_High_Pct": 10.0,
                "Extension_Pct": 0.0,
                "Is_Coiling": False,
                "Sector": "General",
                "Black_Swan_Flag": 0,
                "News": "Neutral",
            }
        ]
    )

    scored = apply_advanced_scoring(df)
    assert not scored.loc[0, "Quality_Gate_Pass"]
    assert scored.loc[0, "Score"] == 0
    assert scored.loc[0, "Verdict"] == "❌ FAIL"


def test_missing_market_cap_does_not_zero_score():
    df = pd.DataFrame(
        [
            {
                "Symbol": "TEST",
                "Score": 55,
                "Price": 100.0,
                "Avg_Value_20D_Cr": 12.0,
                "Market_Cap_Cr": 0.0,
                "Debt_To_Equity": 0.5,
                "Technical_Raw": 60.0,
                "Fundamental_Raw": 60.0,
                "Sentiment_Raw": 60.0,
                "Context_Raw": 60.0,
                "RSI": 55.0,
                "RS_Score": 0.0,
                "RS_Composite": 1.0,
                "Vol_Surge_Ratio": 1.0,
                "Dist_52W_High_Pct": 10.0,
                "Extension_Pct": 0.0,
                "Is_Coiling": False,
                "Sector": "General",
                "Black_Swan_Flag": 0,
                "News": "Neutral",
            }
        ]
    )

    scored = apply_advanced_scoring(df)
    assert scored.loc[0, "Quality_Gate_Pass"]
    assert scored.loc[0, "Score"] > 0
    assert "MCap<1500.0Cr" not in scored.loc[0, "Quality_Gate_Failures"]


def test_apply_quality_gates_marks_failure_reasons():
    df = pd.DataFrame(
        [
            {
                "Price": 60.0,
                "Avg_Value_20D_Cr": 2.0,
                "Market_Cap_Cr": 1000.0,
                "Debt_To_Equity": 3.5,
                "Liquidity_Flag": "Low Liquidity - Avoid",
            }
        ]
    )
    cfg = {
        "liquidity_cr_min": 8.0,
        "price_min": 80.0,
        "market_cap_cr_min": 1500.0,
        "max_debt_to_equity": 2.0,
    }

    gated = _apply_quality_gates(df, cfg)
    assert not gated.loc[0, "Quality_Gate_Pass"]
    failures = gated.loc[0, "Quality_Gate_Failures"]
    assert "Liquidity<8.0Cr" in failures
    assert "Price<80.0" in failures
    assert "MCap<1500.0Cr" in failures
    assert "Debt/Equity>2.0" in failures
    assert "LowLiquidityFlag" in failures


def test_prepare_screener_table_renames_and_orders_ai_score():
    df = pd.DataFrame(
        [
            {
                "Symbol": "TEST",
                "Score": 72.5,
                "ai_score": 81.2,
                "Quality_Gate_Failures": "",
            }
        ]
    )

    table_df = prepare_screener_table(df, feature_ai_enabled=True)
    assert "Conviction Score" in table_df.columns
    assert "AI Score" in table_df.columns
    assert (
        table_df.columns.tolist().index("AI Score")
        == table_df.columns.tolist().index("Conviction Score") + 1
    )
    assert "Gate Failures" in table_df.columns


def test_score_mod_is_applied_once_via_fallback_resolution():
    # If the old double-counting came back, this would effectively double-penalize.
    assert _resolve_conviction_score(0, 60, -20) == 40


def test_check_institutional_fortress_applies_score_mod_once(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=210, freq="D")
    data = pd.DataFrame(
        {
            "Close": [100.0] * 210,
            "High": [101.0] * 210,
            "Low": [99.0] * 210,
            "Open": [100.0] * 210,
            "Volume": [1000.0] * 210,
        },
        index=idx,
    )

    class _TA:
        @staticmethod
        def ema(series, length):
            value = {200: 90.0, 50: 95.0, 20: 98.0, 30: 92.0}.get(length, 90.0)
            return pd.Series([value] * len(series), index=series.index)

        @staticmethod
        def rsi(series, length):
            return pd.Series([55.0] * len(series), index=series.index)

        @staticmethod
        def atr(high, low, close, length):
            value = 1.0 if length == 14 else 2.0
            return pd.Series([value] * len(close), index=close.index)

        @staticmethod
        def supertrend(high, low, close, length, multiplier):
            return pd.DataFrame({"SUPERTd_10_3": [1] * len(close)}, index=close.index)

        @staticmethod
        def adx(high, low, close, length):
            return pd.DataFrame({"ADX_14": [30.0] * len(close)}, index=close.index)

    monkeypatch.setattr(logic, "ta", _TA)
    monkeypatch.setattr(
        logic,
        "_get_ticker_news",
        lambda symbol: [{"title": "Fraud probe", "summary": ""}],
    )
    monkeypatch.setattr(
        logic,
        "_get_ticker_calendar",
        lambda symbol: pd.DataFrame(
            [[datetime.now().date() + timedelta(days=3)]], columns=["date"]
        ),
    )
    monkeypatch.setattr(
        logic, "_get_ticker_earnings_dates", lambda symbol: pd.DataFrame()
    )
    monkeypatch.setattr(logic, "_get_ticker_info", lambda symbol: {})
    monkeypatch.setattr(
        logic,
        "_get_benchmark_series",
        lambda symbol: pd.Series([100.0] * len(data), index=data.index),
    )

    result = logic.check_institutional_fortress(
        ticker="TEST",
        data=data,
        ticker_obj=None,
        portfolio_value=1_000_000,
        risk_per_trade=0.01,
        selected_universe="NIFTY50",
        regime_data={"Market_Regime": "Range", "Regime_Multiplier": 1.0, "VIX": 20.0},
    )

    assert result is not None
    assert result["Score"] == 38
    assert result["News"] == "🚨 BLACK SWAN"
    assert result["Events"].startswith("🚨 EARNINGS")


def test_prepare_screener_table_renders_conviction_and_ai_scores(tmp_path):
    script = tmp_path / "render_screener.py"
    script.write_text("""
import sys
sys.path.insert(0, "/Users/shivamdixit/Desktop/fortress-dashboard/engine")
import streamlit as st
import pandas as pd
from stock_scanner.ui_helpers import prepare_screener_table

df = pd.DataFrame([{"Score": 12, "ai_score": 34, "Quality_Gate_Failures": ""}])
st.dataframe(prepare_screener_table(df, True), hide_index=True)
""")

    app = AppTest.from_file(str(script)).run()
    assert len(app.dataframe) == 1
    rendered = app.dataframe[0].value
    assert list(rendered.columns) == ["Conviction Score", "AI Score", "Gate Failures"]
    assert rendered.iloc[0]["Conviction Score"] == 12
    assert rendered.iloc[0]["AI Score"] == 34
