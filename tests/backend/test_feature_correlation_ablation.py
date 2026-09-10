import json
import sqlite3

import pytest
from research.feature_correlation_ablation import (
    analyze_dataset,
    generate_markdown_report,
    write_report,
)


def _dataset() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
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
    rows = [
        (
            "2025-01-01",
            "AAA",
            80.0,
            {
                "Dist_52W_High_Pct": 4.0,
                "RS_Score": 8.0,
                "Vol_Surge_Ratio": 2.0,
                "Feature_Contributions": {
                    "Dist_52W_High_Pct": 15.0,
                    "RS_Score": 8.0,
                    "Vol_Surge_Ratio": 10.0,
                },
            },
        ),
        (
            "2025-01-01",
            "BBB",
            50.0,
            {
                "Dist_52W_High_Pct": 30.0,
                "RS_Score": -4.0,
                "Vol_Surge_Ratio": 1.0,
                "Feature_Contributions": {
                    "Dist_52W_High_Pct": -10.0,
                    "RS_Score": -10.0,
                    "Vol_Surge_Ratio": 0.0,
                },
            },
        ),
        (
            "2025-01-02",
            "CCC",
            65.0,
            {
                "Dist_52W_High_Pct": 10.0,
                "RS_Score": 2.0,
                "Vol_Surge_Ratio": 1.5,
                "Feature_Contributions": {
                    "Dist_52W_High_Pct": 8.0,
                    "RS_Score": 8.0,
                    "Vol_Surge_Ratio": 10.0,
                },
            },
        ),
    ]
    db.executemany(
        "INSERT INTO observations VALUES (?, ?, ?, ?)",
        [(d, s, score, json.dumps(features)) for d, s, score, features in rows],
    )
    db.executemany(
        "INSERT INTO labels VALUES (?, ?, ?, ?, ?)",
        [
            ("2025-01-01", "AAA", 5, 0.10, "ok"),
            ("2025-01-01", "BBB", 5, -0.02, "ok"),
            ("2025-01-02", "CCC", 5, 0.04, "ok"),
        ],
    )
    return db


def test_analyzer_reports_correlations_contributions_and_exact_ablation():
    report = analyze_dataset(_dataset())

    assert report["metadata"]["observation_count"] == 3
    assert report["correlation"]["pearson"]["RS_Score"]["Vol_Surge_Ratio"] == pytest.approx(
        1.0
    )
    rs = report["contributions"]["RS_Score"]
    assert rs["sample_size"] == 3
    assert rs["score_pearson"] > 0.9

    ablation = report["ablations"]["individual"]["RS_Score"]
    assert ablation["status"] == "exact"
    assert ablation["score_delta_mean"] == pytest.approx(-2.0)
    assert ablation["rank_spearman"] < 1.0
    assert ablation["forward_return_impact"]["5"]["baseline_mean_return"] == pytest.approx(
        0.10
    )


def test_missing_contribution_evidence_is_not_silent():
    db = _dataset()
    db.execute(
        "UPDATE observations SET features_json = ? WHERE symbol = 'CCC'",
        (json.dumps({"RS_Score": 2.0}),),
    )
    report = analyze_dataset(db)

    assert report["ablations"]["individual"]["RS_Score"]["status"] == "unsupported"
    assert report["ablations"]["individual"]["RS_Score"]["unsupported_rows"] == 1


def test_markdown_report_is_deterministic_and_explicit():
    markdown = generate_markdown_report(analyze_dataset(_dataset()))

    assert "# FORTRESS-R3 Feature Correlation and Ablation Report" in markdown
    assert "Exact ablation evidence" in markdown
    assert "RS_Score" in markdown


def test_write_report_creates_reproducible_artifacts(tmp_path):
    write_report(analyze_dataset(_dataset()), tmp_path)

    assert {
        path.name for path in tmp_path.iterdir()
    } == {
        "r3_feature_ablation.json",
        "r3_feature_ablation.md",
        "r3_ablation_table.csv",
    }
    payload = json.loads((tmp_path / "r3_feature_ablation.json").read_text())
    assert payload["metadata"]["methodology"].startswith("FORTRESS-R3")
