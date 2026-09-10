"""
tests/backend/test_data_quality_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the Fortress Market Data Quality Contract (engine/utils/data_quality.py).

Verifies:
  1. Minimum history requirement (insufficient rows/coverage detection).
  2. Missing trading days tracking and expected day computation.
  3. Stale data & missing recent sessions detection.
  4. Duplicate dates detection.
  5. Malformed OHLC detection:
     - High < Low
     - Open outside [Low, High]
     - Close outside [Low, High]
     - Non-positive prices (<= 0)
     - Null / NaN / Inf values
     - Negative volume (< 0)
     - Flat prices warning
  6. Multi-symbol universe & batch quality evaluation:
     - Empty universe
     - Missing symbols
     - Unexpected universe shrinkage below retention floor
  7. Explicit quality states: VALID, WARNING, INVALID.
  8. Observable reporting schema (to_dict, summary, tracking fields).
"""

from datetime import date, datetime, timedelta, timezone
import numpy as np
import pandas as pd
import pytest

from utils import market_data_provider as mdp
from utils.data_quality import (
    DataQualityStatus,
    IssueSeverity,
    QualityContractConfig,
    QualityIssue,
    SymbolQualityReport,
    UniverseQualityReport,
    validate_market_universe,
    validate_symbol_ohlcv,
)


def _make_valid_ohlcv(
    start_date: str = "2025-01-01",
    days: int = 220,
    base_price: float = 100.0,
    symbol: str = "TCS.NS",
) -> pd.DataFrame:
    """Generate a clean synthetic daily OHLCV DataFrame."""
    dates = pd.bdate_range(start=start_date, periods=days)
    np.random.seed(42)
    
    rows = []
    current_price = base_price
    for d in dates:
        step = np.random.uniform(-1.5, 1.5)
        o = round(current_price + step, 2)
        h = round(o + np.random.uniform(0.5, 3.0), 2)
        l = round(o - np.random.uniform(0.5, 3.0), 2)
        c = round(np.random.uniform(l, h), 2)
        v = int(np.random.uniform(10_000, 500_000))
        rows.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v})
        current_price = c

    df = pd.DataFrame(rows, index=dates)
    return df


# ---------------------------------------------------------------------------
# 1. Valid Data Baseline & Observable Fields
# ---------------------------------------------------------------------------


def test_valid_ohlcv_passes_contract():
    df = _make_valid_ohlcv(days=250)
    last_date = df.index[-1].date()
    cfg = QualityContractConfig(
        min_history_rows=210,
        reference_date=last_date,  # No staleness
        max_stale_days=5,
    )
    
    report = validate_symbol_ohlcv(symbol="TCS.NS", df=df, source="bhavcopy", config=cfg)
    
    assert report.status == DataQualityStatus.VALID
    assert report.is_valid is True
    assert report.is_invalid is False
    assert report.is_warning is False
    assert report.symbol == "TCS.NS"
    assert report.source == "bhavcopy"
    assert report.row_count == 250
    assert report.stale_days == 0
    assert report.coverage_pct >= 95.0
    assert report.first_available_date == str(df.index[0].date())
    assert report.last_available_date == str(df.index[-1].date())
    assert len(report.issues) == 0
    
    # Check serialization
    d = report.to_dict()
    assert d["status"] == "valid"
    assert d["row_count"] == 250
    assert "data_timestamp" in d
    assert isinstance(d["coverage_pct"], float)
    assert "[VALID]" in report.summary()


def test_mdp_validate_ohlcv_helper():
    df = _make_valid_ohlcv(days=250)
    last_date = df.index[-1].date()
    cfg = QualityContractConfig(reference_date=last_date)
    report = mdp.validate_ohlcv("TCS.NS", df, source="indstocks", config=cfg)
    assert report.status == DataQualityStatus.VALID
    assert report.source == "indstocks"


# ---------------------------------------------------------------------------
# 2. Missing Data & Empty Symbols
# ---------------------------------------------------------------------------


def test_empty_or_none_dataframe_is_invalid():
    report_none = validate_symbol_ohlcv("RELIANCE.NS", None, source="bhavcopy")
    assert report_none.status == DataQualityStatus.INVALID
    assert report_none.is_invalid is True
    assert report_none.row_count == 0
    assert any(i.code == "MISSING_DATA" for i in report_none.issues)

    report_empty = validate_symbol_ohlcv("RELIANCE.NS", pd.DataFrame(), source="yfinance")
    assert report_empty.status == DataQualityStatus.INVALID
    assert any(i.code == "MISSING_DATA" for i in report_empty.issues)


# ---------------------------------------------------------------------------
# 3. Minimum History & Coverage Requirements
# ---------------------------------------------------------------------------


def test_insufficient_history_fails_contract():
    # Only 50 rows when 210 are required
    df = _make_valid_ohlcv(days=50)
    last_date = df.index[-1].date()
    cfg = QualityContractConfig(min_history_rows=210, reference_date=last_date)
    
    report = validate_symbol_ohlcv("INFY.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert report.row_count == 50
    issue_codes = [i.code for i in report.issues]
    assert "INSUFFICIENT_HISTORY" in issue_codes


def test_short_period_allows_appropriate_history():
    # A "1mo" request with 22 rows should not fail the 210-row scanner floor
    df = _make_valid_ohlcv(days=22)
    last_date = df.index[-1].date()
    cfg = QualityContractConfig(
        period="1mo",
        min_history_rows=210,
        min_coverage_pct=70.0,
        reference_date=last_date,
    )
    report = validate_symbol_ohlcv("HDFCBANK.NS", df, config=cfg)
    assert report.status == DataQualityStatus.VALID


# ---------------------------------------------------------------------------
# 4. Duplicate Dates
# ---------------------------------------------------------------------------


def test_duplicate_dates_detected_as_invalid():
    df = _make_valid_ohlcv(days=220)
    # Duplicate the 10th row with the same index timestamp
    df_dupe = pd.concat([df.iloc[:10], df.iloc[9:10], df.iloc[10:]])
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("SBIN.NS", df_dupe, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "DUPLICATE_DATES" for i in report.issues)


# ---------------------------------------------------------------------------
# 5. Malformed OHLC Relationships & Impossible Values
# ---------------------------------------------------------------------------


def test_high_less_than_low_is_invalid():
    df = _make_valid_ohlcv(days=220)
    # Corrupt one row: High = 90, Low = 110
    df.iloc[15, df.columns.get_loc("High")] = 90.0
    df.iloc[15, df.columns.get_loc("Low")] = 110.0
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("ITC.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "INVALID_HIGH_LOW" for i in report.issues)


def test_open_outside_high_low_is_invalid():
    df = _make_valid_ohlcv(days=220)
    # Open higher than High
    high_val = df.iloc[20]["High"]
    df.iloc[20, df.columns.get_loc("Open")] = high_val + 10.0
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("LT.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "OPEN_OUTSIDE_HIGH_LOW" for i in report.issues)


def test_close_outside_high_low_is_invalid():
    df = _make_valid_ohlcv(days=220)
    # Close lower than Low
    low_val = df.iloc[25]["Low"]
    df.iloc[25, df.columns.get_loc("Close")] = low_val - 10.0
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("AXISBANK.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "CLOSE_OUTSIDE_HIGH_LOW" for i in report.issues)


def test_non_positive_price_is_invalid():
    df = _make_valid_ohlcv(days=220)
    # Set price <= 0
    df.iloc[30, df.columns.get_loc("Low")] = 0.0
    df.iloc[30, df.columns.get_loc("Close")] = 0.0
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("MARUTI.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "NON_POSITIVE_PRICE" for i in report.issues)


def test_negative_volume_is_invalid():
    df = _make_valid_ohlcv(days=220)
    df.iloc[40, df.columns.get_loc("Volume")] = -500
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("WIPRO.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "NEGATIVE_VOLUME" for i in report.issues)


def test_null_and_inf_values_are_invalid():
    df = _make_valid_ohlcv(days=220)
    df.iloc[12, df.columns.get_loc("Open")] = np.nan
    df.iloc[14, df.columns.get_loc("Close")] = np.inf
    
    cfg = QualityContractConfig(reference_date=df.index[-1].date())
    report = validate_symbol_ohlcv("TATAMOTORS.NS", df, config=cfg)
    
    assert report.status == DataQualityStatus.INVALID
    codes = [i.code for i in report.issues]
    assert "NULL_VALUES" in codes
    assert "INF_VALUES" in codes


# ---------------------------------------------------------------------------
# 6. Staleness & Missing Recent Sessions
# ---------------------------------------------------------------------------


def test_stale_data_is_detected_and_flagged():
    df = _make_valid_ohlcv(days=220)
    # Last date is 15 business days behind reference date
    last_date = df.index[-1].date()
    future_ref_date = last_date + timedelta(days=25)
    
    cfg = QualityContractConfig(
        reference_date=future_ref_date,
        max_stale_days=5,
    )
    report = validate_symbol_ohlcv("BHARTIARTL.NS", df, config=cfg)
    
    assert report.stale_days > 5
    assert any(i.code == "STALE_DATA" for i in report.issues)
    assert report.status in (DataQualityStatus.WARNING, DataQualityStatus.INVALID)


def test_flat_prices_detected_as_warning():
    df = _make_valid_ohlcv(days=220)
    # Freeze close price for last 20 rows
    frozen_price = 150.0
    df.iloc[-20:, df.columns.get_loc("Open")] = frozen_price
    df.iloc[-20:, df.columns.get_loc("High")] = frozen_price
    df.iloc[-20:, df.columns.get_loc("Low")] = frozen_price
    df.iloc[-20:, df.columns.get_loc("Close")] = frozen_price
    
    cfg = QualityContractConfig(
        reference_date=df.index[-1].date(),
        check_flat_prices=True,
        max_consecutive_flat_days=15,
    )
    report = validate_symbol_ohlcv("ILLIQUID.NS", df, config=cfg)
    
    assert any(i.code == "FLAT_PRICES_DETECTED" for i in report.issues)
    assert report.status == DataQualityStatus.WARNING


# ---------------------------------------------------------------------------
# 7. Universe Validation & Shrinkage Detection
# ---------------------------------------------------------------------------


def test_empty_universe_is_invalid():
    report = validate_market_universe(data={}, expected_symbols=[])
    assert report.status == DataQualityStatus.INVALID
    assert any(i.code == "EMPTY_UNIVERSE" for i in report.issues)


def test_universe_with_missing_symbols_and_shrinkage():
    expected = ["TCS.NS", "INFY.NS", "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
    
    # Only 2 out of 5 symbols are present -> 40% retention (below 80% default floor)
    data = {
        "TCS.NS": _make_valid_ohlcv(days=220, symbol="TCS.NS"),
        "INFY.NS": _make_valid_ohlcv(days=220, symbol="INFY.NS"),
    }
    
    ref_date = data["TCS.NS"].index[-1].date()
    cfg = QualityContractConfig(
        reference_date=ref_date,
        min_universe_retention_ratio=0.8,
    )
    
    universe_report = validate_market_universe(data=data, expected_symbols=expected, config=cfg)
    
    assert universe_report.status == DataQualityStatus.INVALID
    assert universe_report.total_symbols_expected == 5
    assert universe_report.valid_count == 2
    assert universe_report.missing_count == 3
    assert set(universe_report.missing_symbols) == {"RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS"}
    
    issue_codes = [i.code for i in universe_report.issues]
    assert "MISSING_SYMBOLS" in issue_codes
    assert "UNEXPECTED_UNIVERSE_SHRINKAGE" in issue_codes
    
    d = universe_report.to_dict()
    assert d["total_symbols_expected"] == 5
    assert d["valid_count"] == 2
    assert "symbol_reports" in d
    assert "TCS.NS" in d["symbol_reports"]
    assert "Universe [INVALID]" in universe_report.summary()


def test_full_healthy_universe_passes():
    symbols = ["TCS.NS", "INFY.NS", "RELIANCE.NS"]
    dfs = {s: _make_valid_ohlcv(days=220, symbol=s) for s in symbols}
    ref_date = dfs["TCS.NS"].index[-1].date()
    cfg = QualityContractConfig(reference_date=ref_date)
    
    report = mdp.validate_universe(dfs, symbols, source="bhavcopy", config=cfg)
    assert report.status == DataQualityStatus.VALID
    assert report.valid_count == 3
    assert report.coverage_ratio == 1.0
    assert len(report.missing_symbols) == 0
