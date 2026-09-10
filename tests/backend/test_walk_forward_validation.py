import json
import sqlite3
from datetime import date, timedelta

import pytest
from research.walk_forward_validation import (
    STEP_SESSIONS,
    TEST_SESSIONS,
    TRAIN_SESSIONS,
    VALIDATION_SESSIONS,
    analyze_dataset,
    generate_markdown_report,
    write_report,
)


def _sessions(count=504):
    values = []
    current = date(2024, 1, 1)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def _dataset():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE sessions (date TEXT PRIMARY KEY, cutoff TEXT NOT NULL);
        CREATE TABLE observations (
            date TEXT, symbol TEXT, fortress_score REAL,
            features_json TEXT NOT NULL
        );
        CREATE TABLE labels (
            date TEXT, symbol TEXT, horizon INTEGER,
            forward_return REAL, status TEXT
        );
        """
    )
    days = _sessions()
    db.executemany(
        "INSERT INTO sessions VALUES (?, ?)",
        [(day, f"{day}T16:00:00+05:30") for day in days],
    )
    symbols = [
        ("AAA", 90.0, 0.10, 0.90),
        ("BBB", 80.0, 0.06, 0.70),
        ("CCC", 60.0, 0.02, 0.50),
        ("DDD", 40.0, -0.02, 0.20),
        ("NIFTY", None, 0.03, None),
    ]
    observations = []
    labels = []
    for index, day in enumerate(days):
        for symbol, score, forward_return, rs_score in symbols:
            observations.append(
                (
                    day,
                    symbol,
                    score,
                    json.dumps(
                        {"RS_Score": rs_score} if rs_score is not None else {}
                    ),
                )
            )
            labels.append((day, symbol, 5, forward_return, "ok"))
    db.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", observations)
    db.executemany("INSERT INTO labels VALUES (?, ?, ?, ?, ?)", labels)
    return db


def test_windows_are_ordered_disjoint_and_use_declared_geometry():
    report = analyze_dataset(_dataset(), top_n=(1,), horizon=5)

    assert report["configuration"]["train_sessions"] == TRAIN_SESSIONS
    assert report["configuration"]["validation_sessions"] == VALIDATION_SESSIONS
    assert report["configuration"]["test_sessions"] == TEST_SESSIONS
    assert report["configuration"]["step_sessions"] == STEP_SESSIONS
    windows = report["windows"]
    assert len(windows) == 3
    first = windows[0]
    assert first["train"]["count"] == 252
    assert first["validation"]["count"] == 63
    assert first["test"]["count"] == 63
    assert set(first["train"]["dates"]).isdisjoint(first["validation"]["dates"])
    assert set(first["validation"]["dates"]).isdisjoint(first["test"]["dates"])
    assert windows[1]["train"]["dates"][0] == windows[0]["train"]["dates"][63]


def test_metrics_compare_fortress_momentum_equal_and_nifty():
    report = analyze_dataset(_dataset(), top_n=(1,), horizon=5)

    metrics = report["windows"][0]["metrics"]["test"]
    fortress = metrics["top_n"]["1"]
    momentum = metrics["momentum_top_n"]["1"]
    equal = metrics["equal_universe"]

    assert fortress["sample_size"] == 63
    assert fortress["mean_return"] == pytest.approx(0.10)
    assert fortress["win_rate"] == pytest.approx(1.0)
    assert fortress["benchmark_excess_return"] == pytest.approx(0.07)
    assert fortress["max_drawdown"] == pytest.approx(0.0)
    assert momentum["mean_return"] == pytest.approx(0.10)
    assert equal["mean_return"] == pytest.approx(0.04)
    assert metrics["nifty"]["mean_return"] == pytest.approx(0.03)


def test_score_buckets_and_oos_degradation_are_reported():
    report = analyze_dataset(_dataset(), top_n=(1,), horizon=5)

    bucket = report["windows"][0]["metrics"]["test"]["score_buckets"]["90-100"]
    assert bucket["sample_size"] == 63
    assert bucket["mean_return"] == pytest.approx(0.10)
    summary = report["aggregate"]["top_n"]["1"]
    assert summary["in_sample"]["sample_size"] > 0
    assert summary["out_of_sample"]["sample_size"] == 63 * 3
    assert "degradation" in summary


def test_turnover_is_deterministic_and_reports_missing_labels():
    db = _dataset()
    db.execute(
        "UPDATE labels SET status = 'missing_target_price', forward_return = NULL "
        "WHERE symbol = 'AAA' AND date = ("
        "SELECT date FROM sessions ORDER BY date LIMIT 1 OFFSET 315)"
    )
    report = analyze_dataset(db, top_n=(1,), horizon=5)

    portfolio = report["windows"][0]["metrics"]["test"]["top_n"]["1"]
    assert portfolio["missing_return_count"] == 1
    assert 0.0 <= portfolio["turnover"] <= 2.0


def test_report_artifacts_are_reproducible(tmp_path):
    report = analyze_dataset(_dataset(), top_n=(1,), horizon=5)
    write_report(report, tmp_path)

    assert {
        path.name for path in tmp_path.iterdir()
    } == {
        "r4_walk_forward.json",
        "r4_windows.csv",
        "r4_metrics.csv",
        "r4_walk_forward.md",
    }
    markdown = generate_markdown_report(report)
    assert "# FORTRESS-R4 Walk-Forward Out-of-Sample Validation" in markdown
    assert "Untouched evaluation period" in markdown
