"""
tests/backend/test_forward_return_validation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Regression and methodology tests for FORTRESS-R2 score forward-return validation.
"""

import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
import pytest

from research.forward_return_validation import (
    SCORE_BUCKETS,
    CORE_SCORE_BUCKETS,
    HORIZONS,
    REGIMES,
    BucketHorizonMetrics,
    ValidationReport,
    _assign_bucket,
    _compute_spearman_rank_correlation,
    _compute_stats,
    _percentile,
    compute_mae_for_observations,
    generate_markdown_report,
    run_forward_return_validation,
)
from research.historical_dataset import build_dataset


def _create_synthetic_r1_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fully formed R1 SQLite database with synthetic score distributions across regimes."""
    days = []
    current = date(2025, 1, 2)
    while len(days) < 65:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)

    symbols = ["TCS", "INFY", "RELIANCE", "HDFCBANK", "NIFTY"]
    
    # Write jsonl files
    (tmp_path / "inputs").mkdir(exist_ok=True)
    digest = hashlib.sha256(b"dummy").hexdigest()
    (tmp_path / "inputs" / digest).write_bytes(b"dummy")

    sessions_data = [{"date": d, "cutoff": d + "T16:00:00+05:30"} for d in days]
    membership_data = [
        {"date": days[0], "symbol": s, "available_at": days[0] + "T09:00:00+05:30"}
        for s in symbols
    ]

    runs_data = [{
        "run_id": "run-20250102",
        "date": days[0],
        "scored_at": days[0] + "T15:30:00+05:30",
        "scoring_revision": "rev-test",
        "scoring_config": {"weights": {"technical": 0.5}},
        "universe": symbols,
        "inputs": [{
            "source": "synthetic",
            "sha256": digest,
            "available_at": days[0] + "T15:00:00+05:30",
            "observed_through": days[0] + "T15:00:00+05:30",
        }],
    }]

    # Create distinct scores and regimes for testing
    snapshots_data = [
        {"run_id": "run-20250102", "symbol": "TCS", "raw_data": {"Score": 92.5, "Market_Regime": "Strong Bull", "RSI": 70, "RS_Score": 85}},
        {"run_id": "run-20250102", "symbol": "INFY", "raw_data": {"Score": 81.0, "Market_Regime": "Bull", "RSI": 62, "RS_Score": 75}},
        {"run_id": "run-20250102", "symbol": "RELIANCE", "raw_data": {"Score": 72.0, "Market_Regime": "Range", "RSI": 52, "RS_Score": 60}},
        {"run_id": "run-20250102", "symbol": "HDFCBANK", "raw_data": {"Score": 55.0, "Market_Regime": "Caution", "RSI": 45, "RS_Score": 40}},
        {"run_id": "run-20250102", "symbol": "NIFTY", "raw_data": {"Score": 60.0, "Market_Regime": "Bull", "RSI": 55, "RS_Score": 50}},
    ]

    # Generate prices with known trajectories:
    # TCS (Score 92.5) -> High positive return
    # INFY (Score 81.0) -> Moderate positive return
    # RELIANCE (Score 72.0) -> Flat return
    # HDFCBANK (Score 55.0) -> Negative return
    # NIFTY -> Benchmark drift (+2% over 60d)
    prices_data = []
    for i, d in enumerate(days):
        prices_data.append({"date": d, "symbol": "TCS", "close": 100.0 * (1.0 + 0.003 * i)})  # +18% by 60d
        prices_data.append({"date": d, "symbol": "INFY", "close": 100.0 * (1.0 + 0.0015 * i)}) # +9% by 60d
        prices_data.append({"date": d, "symbol": "RELIANCE", "close": 100.0 * (1.0 + 0.0002 * i)}) # +1.2%
        prices_data.append({"date": d, "symbol": "HDFCBANK", "close": 100.0 * (1.0 - 0.002 * i)}) # -12%
        prices_data.append({"date": d, "symbol": "NIFTY", "close": 100.0 * (1.0 + 0.0005 * i)})   # +3%

    manifest = {
        "schema_version": 1,
        "calendar": "synthetic-test",
        "price_convention": "unadjusted_close",
        "sources": {"sessions": "s", "membership": "m", "prices": "p"},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    def write_jsonl(path, rows):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    write_jsonl(tmp_path / "sessions.jsonl", sessions_data)
    write_jsonl(tmp_path / "membership.jsonl", membership_data)
    write_jsonl(tmp_path / "runs.jsonl", runs_data)
    write_jsonl(tmp_path / "snapshots.jsonl", snapshots_data)
    write_jsonl(tmp_path / "prices.jsonl", prices_data)

    db_path = tmp_path / "dataset.sqlite"
    build_dataset(tmp_path, db_path)
    return sqlite3.connect(str(db_path))


# ---------------------------------------------------------------------------
# Bucket Assignment & Percentile Helper Tests
# ---------------------------------------------------------------------------


def test_assign_bucket_logic():
    assert _assign_bucket(None) == "missing"
    assert _assign_bucket(45.0) == "<50"
    assert _assign_bucket(50.0) == "50-59"
    assert _assign_bucket(59.99) == "50-59"
    assert _assign_bucket(60.0) == "60-69"
    assert _assign_bucket(75.5) == "70-79"
    assert _assign_bucket(89.0) == "80-89"
    assert _assign_bucket(90.0) == "90-100"
    assert _assign_bucket(100.0) == "90-100"


def test_percentile_calculation():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile(vals, 0.5) == 3.0
    assert _percentile(vals, 0.0) == 1.0
    assert _percentile(vals, 1.0) == 5.0


def test_spearman_rank_correlation_monotonic():
    x = [10.0, 20.0, 30.0, 40.0, 50.0]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    corr = _compute_spearman_rank_correlation(x, y)
    assert pytest.approx(corr, 0.001) == 1.0

    y_inv = [5.0, 4.0, 3.0, 2.0, 1.0]
    corr_inv = _compute_spearman_rank_correlation(x, y_inv)
    assert pytest.approx(corr_inv, 0.001) == -1.0


# ---------------------------------------------------------------------------
# Forward Return Validation Engine Execution Tests
# ---------------------------------------------------------------------------


def test_run_forward_return_validation_synthetic(tmp_path):
    conn = _create_synthetic_r1_db(tmp_path)
    report = run_forward_return_validation(conn, benchmark_symbol="NIFTY")

    assert report.total_observations == 5
    assert report.total_labeled_pairs == 20  # 5 symbols * 4 horizons (5D, 10D, 20D, 60D)
    assert set(report.horizons) == {5, 10, 20, 60}

    # Verify 60D metrics
    m_60 = report.overall_bucket_metrics[60]
    assert m_60["90-100"].sample_size == 1
    assert m_60["90-100"].mean_return > 0.15  # TCS gained ~18%
    assert m_60["90-100"].win_rate == 1.0

    assert m_60["50-59"].sample_size == 1
    assert m_60["50-59"].mean_return < 0.0   # HDFCBANK lost ~12%
    assert m_60["50-59"].negative_return_freq == 1.0

    # Monotonicity / rank correlation check across scores vs returns
    corr_60 = report.rank_correlation_by_horizon[60]
    assert corr_60 >= 0.89  # Strong positive rank correlation in this synthetic set

    # Benchmark comparison
    base_60 = report.baselines[60]
    assert base_60.benchmark_mean_return is not None
    assert m_60["90-100"].benchmark_excess_return > 0.10

    # Top momentum baseline
    assert base_60.top_momentum_mean_return is not None

    # Regime breakdown checks
    strong_bull_m = report.regime_bucket_metrics["Strong Bull"][60]["90-100"]
    assert strong_bull_m.sample_size == 1
    assert strong_bull_m.mean_return > 0.15

    caution_m = report.regime_bucket_metrics["Caution"][60]["50-59"]
    assert caution_m.sample_size == 1
    assert caution_m.mean_return < 0.0

    # Summary findings generated
    assert len(report.summary_findings) == 4

    # Serialization
    d = report.to_dict()
    assert d["total_observations"] == 5
    assert "overall_bucket_metrics" in d
    assert "baselines" in d


def test_markdown_report_generation(tmp_path):
    conn = _create_synthetic_r1_db(tmp_path)
    report = run_forward_return_validation(conn, benchmark_symbol="NIFTY")
    md = generate_markdown_report(report)

    assert "# Fortress Score Forward-Return Validation Report" in md
    assert "Horizon: 60 Exchange Sessions (60D)" in md
    assert "Regime: Strong Bull" in md
    assert "Association vs. Predictive Value vs. Tradable Strategy Evidence" in md
