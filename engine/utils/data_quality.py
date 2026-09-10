"""
engine/utils/data_quality.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Formal reusable data-quality contract for Fortress market data.

Tracks observable quality metrics and enforces strict anomaly detection:
  - Insufficient history
  - Missing recent sessions / stale data
  - Duplicate dates
  - Invalid OHLC relationships (High < Low, Open/Close outside High-Low range)
  - Impossible prices / negative volumes
  - Missing symbols
  - Unexpected universe shrinkage

Quality states are explicitly modeled:
  - VALID: Data passes all quality gates and integrity checks.
  - WARNING: Minor anomalies or non-fatal staleness that may affect analytics.
  - INVALID: Malformed, missing, corrupted, or insufficient data that must
             never be silently treated as valid.

This contract is reusable across all market data sources (Bhav Copy, INDstocks,
yfinance, CSV, manual feeds).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Union

import numpy as np
import pandas as pd


class DataQualityStatus(str, Enum):
    """Explicit market data quality status."""
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


class IssueSeverity(str, Enum):
    """Severity of a detected quality issue."""
    WARNING = "warning"
    ERROR = "error"


@dataclass
class QualityIssue:
    """Individual quality violation or warning."""
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.ERROR
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value if isinstance(self.severity, IssueSeverity) else str(self.severity),
            "details": self.details or {},
        }


@dataclass
class QualityContractConfig:
    """Configurable thresholds for market data validation."""
    min_history_rows: int = 210
    min_coverage_pct: float = 70.0
    max_stale_days: int = 5  # Trading days
    reference_date: Optional[date] = None  # Reference 'as-of' date; defaults to today UTC
    require_volume: bool = True
    allow_zero_volume: bool = False
    check_flat_prices: bool = True
    max_consecutive_flat_days: int = 15
    period: Optional[str] = None
    min_universe_retention_ratio: float = 0.8  # Minimum fraction of valid symbols in universe

    def get_reference_date(self) -> date:
        if self.reference_date is not None:
            return self.reference_date
        return datetime.now(tz=timezone.utc).date()


@dataclass
class SymbolQualityReport:
    """Observable quality contract report for a single symbol's market data."""
    symbol: str
    source: str = "unknown"
    status: DataQualityStatus = DataQualityStatus.VALID
    first_available_date: Optional[str] = None
    last_available_date: Optional[str] = None
    row_count: int = 0
    expected_trading_days: int = 0
    missing_trading_days: List[str] = field(default_factory=list)
    stale_days: int = 0
    coverage_pct: float = 0.0
    data_timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )
    issues: List[QualityIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == DataQualityStatus.VALID

    @property
    def is_warning(self) -> bool:
        return self.status == DataQualityStatus.WARNING

    @property
    def is_invalid(self) -> bool:
        return self.status == DataQualityStatus.INVALID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "status": self.status.value if isinstance(self.status, DataQualityStatus) else str(self.status),
            "first_available_date": self.first_available_date,
            "last_available_date": self.last_available_date,
            "row_count": self.row_count,
            "expected_trading_days": self.expected_trading_days,
            "missing_trading_days": self.missing_trading_days,
            "stale_days": self.stale_days,
            "coverage_pct": round(self.coverage_pct, 2),
            "data_timestamp": self.data_timestamp,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def summary(self) -> str:
        issue_msgs = "; ".join(f"[{i.code}] {i.message}" for i in self.issues)
        issues_str = f" | Issues: {issue_msgs}" if self.issues else ""
        return (
            f"[{self.status.value.upper()}] {self.symbol} ({self.source}): "
            f"{self.row_count}/{self.expected_trading_days} rows ({self.coverage_pct:.1f}% cov), "
            f"stale={self.stale_days}d, range={self.first_available_date}..{self.last_available_date}"
            f"{issues_str}"
        )


@dataclass
class UniverseQualityReport:
    """Observable quality contract report for a market data universe/batch."""
    total_symbols_expected: int
    total_symbols_evaluated: int
    valid_count: int
    warning_count: int
    invalid_count: int
    missing_count: int
    missing_symbols: List[str] = field(default_factory=list)
    coverage_ratio: float = 0.0
    status: DataQualityStatus = DataQualityStatus.VALID
    symbol_reports: Dict[str, SymbolQualityReport] = field(default_factory=dict)
    issues: List[QualityIssue] = field(default_factory=list)
    data_timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )

    @property
    def is_valid(self) -> bool:
        return self.status == DataQualityStatus.VALID

    @property
    def is_warning(self) -> bool:
        return self.status == DataQualityStatus.WARNING

    @property
    def is_invalid(self) -> bool:
        return self.status == DataQualityStatus.INVALID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_symbols_expected": self.total_symbols_expected,
            "total_symbols_evaluated": self.total_symbols_evaluated,
            "valid_count": self.valid_count,
            "warning_count": self.warning_count,
            "invalid_count": self.invalid_count,
            "missing_count": self.missing_count,
            "missing_symbols": self.missing_symbols,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "status": self.status.value if isinstance(self.status, DataQualityStatus) else str(self.status),
            "symbol_reports": {
                k: v.to_dict() for k, v in self.symbol_reports.items()
            },
            "issues": [issue.to_dict() for issue in self.issues],
            "data_timestamp": self.data_timestamp,
        }

    def summary(self) -> str:
        return (
            f"Universe [{self.status.value.upper()}]: "
            f"{self.valid_count}/{self.total_symbols_expected} valid ({self.coverage_ratio * 100:.1f}%), "
            f"{self.warning_count} warnings, {self.invalid_count} invalid, {self.missing_count} missing"
        )


# Period string -> lookback calendar days
_PERIOD_LOOKBACK_DAYS: Dict[str, int] = {
    "1d": 1,
    "5d": 7,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "3y": 1095,
    "5y": 1825,
}


def _calculate_expected_trading_days(
    start_date: date, end_date: date
) -> list[date]:
    """Calculate expected business/trading days between start_date and end_date (inclusive)."""
    if start_date > end_date:
        return []
    bdate_range = pd.bdate_range(start=start_date, end=end_date)
    return [ts.date() for ts in bdate_range]


def _extract_date_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Extract a normalized date series from DatetimeIndex or Date column."""
    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(df.index.date, index=df.index)
    
    for col in ("Date", "date", "TIMESTAMP", "timestamp", "datetime", "Datetime"):
        if col in df.columns:
            try:
                dt_series = pd.to_datetime(df[col])
                return pd.Series(dt_series.dt.date.values, index=df.index)
            except Exception:
                pass
    return None


def _normalize_ohlcv_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Map DataFrame column variations to standard OHLCV names."""
    col_map = {}
    lower_to_orig = {str(c).lower().strip(): c for c in df.columns}
    
    mappings = {
        "open": ["open", "opnpric", "o"],
        "high": ["high", "hghpric", "h"],
        "low": ["low", "lwpric", "l"],
        "close": ["close", "clspric", "c", "adj close", "adjclose"],
        "volume": ["volume", "vol", "ttltradgvol", "v", "tottrdqty"],
    }
    
    for standard_col, variants in mappings.items():
        for var in variants:
            if var in lower_to_orig:
                col_map[standard_col] = lower_to_orig[var]
                break
                
    return col_map


def validate_symbol_ohlcv(
    symbol: str,
    df: Optional[pd.DataFrame],
    source: str = "unknown",
    config: Optional[QualityContractConfig] = None,
) -> SymbolQualityReport:
    """Validate historical OHLCV data for a single symbol against the quality contract.

    Enforces all core detection rules:
      - Missing data or empty DataFrame
      - Duplicate dates
      - Non-numeric / NaN / Inf values
      - Invalid OHLC relationships (High < Low, Open/Close outside High-Low)
      - Impossible prices (<= 0) and impossible volume (< 0)
      - Insufficient history / coverage
      - Stale data and missing recent sessions
      - Long consecutive flat prices (warning)

    Returns:
        SymbolQualityReport with explicit status (VALID, WARNING, or INVALID).
    """
    cfg = config or QualityContractConfig()
    ref_date = cfg.get_reference_date()
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    
    issues: List[QualityIssue] = []

    # 1. Check for missing/empty DataFrame
    if df is None or df.empty:
        issues.append(
            QualityIssue(
                code="MISSING_DATA",
                message=f"No market data provided for symbol {symbol}",
                severity=IssueSeverity.ERROR,
            )
        )
        return SymbolQualityReport(
            symbol=symbol,
            source=source,
            status=DataQualityStatus.INVALID,
            first_available_date=None,
            last_available_date=None,
            row_count=0,
            expected_trading_days=0,
            missing_trading_days=[],
            stale_days=0,
            coverage_pct=0.0,
            data_timestamp=now_iso,
            issues=issues,
        )

    # 2. Extract and check date sequence
    date_series = _extract_date_series(df)
    if date_series is None or date_series.empty:
        issues.append(
            QualityIssue(
                code="INVALID_DATE_INDEX",
                message="Data lacks a valid DatetimeIndex or Date column",
                severity=IssueSeverity.ERROR,
            )
        )
        return SymbolQualityReport(
            symbol=symbol,
            source=source,
            status=DataQualityStatus.INVALID,
            row_count=len(df),
            data_timestamp=now_iso,
            issues=issues,
        )

    # Check for duplicate dates
    duplicate_count = date_series.duplicated().sum()
    if duplicate_count > 0:
        dupe_dates = [str(d) for d in date_series[date_series.duplicated()].unique()[:5]]
        issues.append(
            QualityIssue(
                code="DUPLICATE_DATES",
                message=f"Detected {duplicate_count} duplicate dates (sample: {dupe_dates})",
                severity=IssueSeverity.ERROR,
                details={"duplicate_count": int(duplicate_count), "sample": dupe_dates},
            )
        )

    # Sorted dates assessment
    dates_list = sorted(date_series.dropna().unique())
    if not dates_list:
        issues.append(
            QualityIssue(
                code="NO_VALID_DATES",
                message="No valid date values found in dataset",
                severity=IssueSeverity.ERROR,
            )
        )
        return SymbolQualityReport(
            symbol=symbol,
            source=source,
            status=DataQualityStatus.INVALID,
            row_count=len(df),
            data_timestamp=now_iso,
            issues=issues,
        )

    first_date = dates_list[0]
    last_date = dates_list[-1]
    row_count = len(df)

    # 3. Normalize & check OHLCV columns
    col_map = _normalize_ohlcv_columns(df)
    missing_required = [c for c in ("open", "high", "low", "close") if c not in col_map]
    if cfg.require_volume and "volume" not in col_map:
        missing_required.append("volume")

    if missing_required:
        issues.append(
            QualityIssue(
                code="MISSING_OHLCV_COLUMNS",
                message=f"Missing required price/volume columns: {missing_required}",
                severity=IssueSeverity.ERROR,
                details={"missing": missing_required, "present": list(df.columns)},
            )
        )
        return SymbolQualityReport(
            symbol=symbol,
            source=source,
            status=DataQualityStatus.INVALID,
            first_available_date=str(first_date),
            last_available_date=str(last_date),
            row_count=row_count,
            data_timestamp=now_iso,
            issues=issues,
        )

    o_col = col_map["open"]
    h_col = col_map["high"]
    l_col = col_map["low"]
    c_col = col_map["close"]
    v_col = col_map.get("volume")

    # 4. Check for Non-Numeric / NaN / Inf values in OHLCV
    ohlc_cols = [o_col, h_col, l_col, c_col]
    if v_col:
        ohlc_cols.append(v_col)

    has_nulls = False
    has_infs = False
    for col in ohlc_cols:
        numeric_series = pd.to_numeric(df[col], errors="coerce")
        null_count = numeric_series.isna().sum()
        inf_count = np.isinf(numeric_series.dropna()).sum()
        if null_count > 0:
            has_nulls = True
            issues.append(
                QualityIssue(
                    code="NULL_VALUES",
                    message=f"Column '{col}' contains {null_count} null or unparseable values",
                    severity=IssueSeverity.ERROR,
                    details={"column": col, "null_count": int(null_count)},
                )
            )
        if inf_count > 0:
            has_infs = True
            issues.append(
                QualityIssue(
                    code="INF_VALUES",
                    message=f"Column '{col}' contains {inf_count} infinite values",
                    severity=IssueSeverity.ERROR,
                    details={"column": col, "inf_count": int(inf_count)},
                )
            )

    if not has_nulls and not has_infs:
        open_val = pd.to_numeric(df[o_col])
        high_val = pd.to_numeric(df[h_col])
        low_val = pd.to_numeric(df[l_col])
        close_val = pd.to_numeric(df[c_col])

        # 5. Check for Impossible Prices (<= 0)
        non_positive_prices = (
            (open_val <= 0) | (high_val <= 0) | (low_val <= 0) | (close_val <= 0)
        )
        if non_positive_prices.any():
            bad_cnt = non_positive_prices.sum()
            issues.append(
                QualityIssue(
                    code="NON_POSITIVE_PRICE",
                    message=f"Found {bad_cnt} rows with non-positive price (<= 0)",
                    severity=IssueSeverity.ERROR,
                    details={"count": int(bad_cnt)},
                )
            )

        # 6. Check Invalid OHLC Relationships
        # High must be >= Low
        high_lt_low = high_val < low_val
        if high_lt_low.any():
            bad_cnt = high_lt_low.sum()
            issues.append(
                QualityIssue(
                    code="INVALID_HIGH_LOW",
                    message=f"Found {bad_cnt} rows where High < Low",
                    severity=IssueSeverity.ERROR,
                    details={"count": int(bad_cnt)},
                )
            )

        # Open must be within [Low, High]
        # (with small epsilon tolerance for float round-off)
        open_out_of_range = (open_val > high_val * 1.00001) | (open_val < low_val * 0.99999)
        if open_out_of_range.any():
            bad_cnt = open_out_of_range.sum()
            issues.append(
                QualityIssue(
                    code="OPEN_OUTSIDE_HIGH_LOW",
                    message=f"Found {bad_cnt} rows where Open is outside High-Low range",
                    severity=IssueSeverity.ERROR,
                    details={"count": int(bad_cnt)},
                )
            )

        # Close must be within [Low, High]
        close_out_of_range = (close_val > high_val * 1.00001) | (close_val < low_val * 0.99999)
        if close_out_of_range.any():
            bad_cnt = close_out_of_range.sum()
            issues.append(
                QualityIssue(
                    code="CLOSE_OUTSIDE_HIGH_LOW",
                    message=f"Found {bad_cnt} rows where Close is outside High-Low range",
                    severity=IssueSeverity.ERROR,
                    details={"count": int(bad_cnt)},
                )
            )

        # 7. Check Impossible Volumes
        if v_col:
            vol_val = pd.to_numeric(df[v_col])
            negative_vol = vol_val < 0
            if negative_vol.any():
                bad_cnt = negative_vol.sum()
                issues.append(
                    QualityIssue(
                        code="NEGATIVE_VOLUME",
                        message=f"Found {bad_cnt} rows with negative volume (< 0)",
                        severity=IssueSeverity.ERROR,
                        details={"count": int(bad_cnt)},
                    )
                )
            if not cfg.allow_zero_volume:
                zero_vol = vol_val == 0
                if zero_vol.all() and row_count > 1:
                    issues.append(
                        QualityIssue(
                            code="ALL_ZERO_VOLUME",
                            message="All rows have exactly 0 volume",
                            severity=IssueSeverity.WARNING,
                        )
                    )

        # 8. Check for completely flat prices over extended period
        if cfg.check_flat_prices and row_count >= cfg.max_consecutive_flat_days:
            # Check if close price hasn't moved at all in the last N sessions
            tail_close = close_val.iloc[-cfg.max_consecutive_flat_days:]
            if tail_close.nunique() == 1:
                issues.append(
                    QualityIssue(
                        code="FLAT_PRICES_DETECTED",
                        message=(
                            f"Close price remained identical ({tail_close.iloc[0]}) "
                            f"over the last {cfg.max_consecutive_flat_days} sessions"
                        ),
                        severity=IssueSeverity.WARNING,
                        details={"flat_price": float(tail_close.iloc[0])},
                    )
                )

    # 9. Calculate expected trading days and coverage
    # Determine the start date for expected range
    expected_start = first_date
    if cfg.period:
        lookback = _PERIOD_LOOKBACK_DAYS.get(cfg.period)
        if lookback:
            period_start = ref_date - timedelta(days=lookback)
            # Use period start if requested period is longer than observed
            expected_start = min(first_date, period_start)

    expected_trading_days_list = _calculate_expected_trading_days(expected_start, ref_date)
    expected_count = len(expected_trading_days_list)

    # Compare present trading days against expected
    present_dates_set = set(dates_list)
    missing_trading_days_list = [
        str(d) for d in expected_trading_days_list if d not in present_dates_set
    ]

    coverage_pct = 0.0
    if expected_count > 0:
        actual_present_in_expected = len([d for d in expected_trading_days_list if d in present_dates_set])
        coverage_pct = (actual_present_in_expected / expected_count) * 100.0
    elif row_count > 0:
        coverage_pct = 100.0

    # 10. Staleness & Missing Recent Sessions Check
    # Stale days = business days between last_date and ref_date
    if last_date >= ref_date:
        stale_days = 0
    else:
        lag_trading_days = _calculate_expected_trading_days(
            last_date + timedelta(days=1), ref_date
        )
        stale_days = len(lag_trading_days)

    if stale_days > cfg.max_stale_days:
        severity = IssueSeverity.ERROR if stale_days > (cfg.max_stale_days * 3) else IssueSeverity.WARNING
        issues.append(
            QualityIssue(
                code="STALE_DATA",
                message=(
                    f"Market data is {stale_days} trading days stale "
                    f"(last available: {last_date}, as-of: {ref_date})"
                ),
                severity=severity,
                details={"stale_days": stale_days, "last_date": str(last_date), "ref_date": str(ref_date)},
            )
        )

    # 11. Insufficient History Check
    if cfg.min_history_rows > 0 and row_count < cfg.min_history_rows:
        # If period explicitly requested was short (e.g. 1mo, 5d), don't fail hard on 210 rows
        if cfg.period and cfg.period in ("1d", "5d", "1mo", "3mo", "6mo"):
            if coverage_pct < cfg.min_coverage_pct:
                issues.append(
                    QualityIssue(
                        code="INSUFFICIENT_COVERAGE",
                        message=(
                            f"Coverage {coverage_pct:.1f}% is below minimum required "
                            f"{cfg.min_coverage_pct:.1f}% for period {cfg.period}"
                        ),
                        severity=IssueSeverity.ERROR,
                        details={"coverage_pct": coverage_pct, "min_coverage_pct": cfg.min_coverage_pct},
                    )
                )
        else:
            issues.append(
                QualityIssue(
                    code="INSUFFICIENT_HISTORY",
                    message=(
                        f"Row count {row_count} is below required minimum history "
                        f"of {cfg.min_history_rows} trading rows"
                    ),
                    severity=IssueSeverity.ERROR,
                    details={"row_count": row_count, "min_history_rows": cfg.min_history_rows},
                )
            )
    elif coverage_pct < cfg.min_coverage_pct:
        issues.append(
            QualityIssue(
                code="INSUFFICIENT_COVERAGE",
                message=(
                    f"Coverage {coverage_pct:.1f}% is below minimum threshold "
                    f"of {cfg.min_coverage_pct:.1f}%"
                ),
                severity=IssueSeverity.WARNING if coverage_pct >= 50.0 else IssueSeverity.ERROR,
                details={"coverage_pct": coverage_pct, "min_coverage_pct": cfg.min_coverage_pct},
            )
        )

    # Determine final status
    has_errors = any(i.severity == IssueSeverity.ERROR for i in issues)
    has_warnings = any(i.severity == IssueSeverity.WARNING for i in issues)

    if has_errors:
        final_status = DataQualityStatus.INVALID
    elif has_warnings:
        final_status = DataQualityStatus.WARNING
    else:
        final_status = DataQualityStatus.VALID

    return SymbolQualityReport(
        symbol=symbol,
        source=source,
        status=final_status,
        first_available_date=str(first_date),
        last_available_date=str(last_date),
        row_count=row_count,
        expected_trading_days=expected_count,
        missing_trading_days=missing_trading_days_list,
        stale_days=stale_days,
        coverage_pct=coverage_pct,
        data_timestamp=now_iso,
        issues=issues,
    )


def validate_market_universe(
    data: Union[Dict[str, pd.DataFrame], pd.DataFrame],
    expected_symbols: Sequence[str],
    source: str = "unknown",
    config: Optional[QualityContractConfig] = None,
) -> UniverseQualityReport:
    """Validate a multi-symbol universe or batch against the quality contract.

    Detects:
      - Empty universe
      - Missing expected symbols
      - Per-symbol anomalies (OHLCV integrity, staleness, history)
      - Unexpected universe shrinkage (valid symbol count drops below threshold)

    Returns:
        UniverseQualityReport with aggregated quality breakdown and status.
    """
    cfg = config or QualityContractConfig()
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    expected_list = list(expected_symbols)
    total_expected = len(expected_list)
    
    issues: List[QualityIssue] = []

    # Handle empty expected universe
    if total_expected == 0:
        issues.append(
            QualityIssue(
                code="EMPTY_UNIVERSE",
                message="Expected universe symbol list is empty",
                severity=IssueSeverity.ERROR,
            )
        )
        return UniverseQualityReport(
            total_symbols_expected=0,
            total_symbols_evaluated=0,
            valid_count=0,
            warning_count=0,
            invalid_count=0,
            missing_count=0,
            missing_symbols=[],
            coverage_ratio=0.0,
            status=DataQualityStatus.INVALID,
            symbol_reports={},
            issues=issues,
            data_timestamp=now_iso,
        )

    # Convert DataFrame with MultiIndex columns (ticker grouping) if needed
    symbol_dfs: Dict[str, pd.DataFrame] = {}
    if isinstance(data, pd.DataFrame):
        if isinstance(data.columns, pd.MultiIndex):
            for sym in expected_list:
                clean_sym = sym.replace(".NS", "").strip()
                match_col = None
                for col_level in (sym, clean_sym, f"{clean_sym}.NS"):
                    if col_level in data.columns.levels[0]:
                        match_col = col_level
                        break
                if match_col:
                    symbol_dfs[sym] = data[match_col].dropna(how="all")
        elif total_expected == 1:
            symbol_dfs[expected_list[0]] = data
    elif isinstance(data, dict):
        for sym in expected_list:
            clean_sym = sym.replace(".NS", "").strip()
            df_item = None
            for key in (sym, clean_sym, f"{clean_sym}.NS"):
                if key in data:
                    df_item = data[key]
                    break
            if df_item is not None:
                symbol_dfs[sym] = df_item

    # Evaluate each expected symbol
    symbol_reports: Dict[str, SymbolQualityReport] = {}
    missing_symbols: List[str] = []
    valid_count = 0
    warning_count = 0
    invalid_count = 0

    for sym in expected_list:
        df_sym = symbol_dfs.get(sym)
        if df_sym is None or df_sym.empty:
            missing_symbols.append(sym)
            report = validate_symbol_ohlcv(
                symbol=sym,
                df=None,
                source=source,
                config=cfg,
            )
            symbol_reports[sym] = report
            invalid_count += 1
        else:
            report = validate_symbol_ohlcv(
                symbol=sym,
                df=df_sym,
                source=source,
                config=cfg,
            )
            symbol_reports[sym] = report
            if report.status == DataQualityStatus.VALID:
                valid_count += 1
            elif report.status == DataQualityStatus.WARNING:
                warning_count += 1
            else:
                invalid_count += 1

    missing_count = len(missing_symbols)
    evaluated_count = len(symbol_dfs)
    coverage_ratio = valid_count / total_expected if total_expected > 0 else 0.0

    # Check for missing symbols
    if missing_symbols:
        issues.append(
            QualityIssue(
                code="MISSING_SYMBOLS",
                message=f"{missing_count} of {total_expected} expected symbols are missing from data",
                severity=IssueSeverity.WARNING if coverage_ratio >= cfg.min_universe_retention_ratio else IssueSeverity.ERROR,
                details={"missing_count": missing_count, "missing_symbols": missing_symbols[:10]},
            )
        )

    # Check for Unexpected Universe Shrinkage
    if coverage_ratio < cfg.min_universe_retention_ratio:
        issues.append(
            QualityIssue(
                code="UNEXPECTED_UNIVERSE_SHRINKAGE",
                message=(
                    f"Universe valid coverage {coverage_ratio * 100:.1f}% fell below "
                    f"retention floor of {cfg.min_universe_retention_ratio * 100:.1f}% "
                    f"({valid_count}/{total_expected} valid symbols)"
                ),
                severity=IssueSeverity.ERROR,
                details={
                    "valid_count": valid_count,
                    "total_expected": total_expected,
                    "coverage_ratio": coverage_ratio,
                    "min_retention_ratio": cfg.min_universe_retention_ratio,
                },
            )
        )

    # Final universe status
    has_errors = any(i.severity == IssueSeverity.ERROR for i in issues)
    has_warnings = any(i.severity == IssueSeverity.WARNING for i in issues)

    if has_errors or valid_count == 0:
        universe_status = DataQualityStatus.INVALID
    elif has_warnings or warning_count > 0 or invalid_count > 0:
        universe_status = DataQualityStatus.WARNING
    else:
        universe_status = DataQualityStatus.VALID

    return UniverseQualityReport(
        total_symbols_expected=total_expected,
        total_symbols_evaluated=evaluated_count,
        valid_count=valid_count,
        warning_count=warning_count,
        invalid_count=invalid_count,
        missing_count=missing_count,
        missing_symbols=missing_symbols,
        coverage_ratio=coverage_ratio,
        status=universe_status,
        symbol_reports=symbol_reports,
        issues=issues,
        data_timestamp=now_iso,
    )
