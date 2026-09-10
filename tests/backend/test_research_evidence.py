"""FORTRESS-V2: tests for the real-R2-evidence loader and its API router.

Covers: valid result, missing result, insufficient sample, stale result,
malformed result, score at a bucket boundary, and regime fallback. No
fixture/illustrative data is ever asserted as an acceptable substitute for
a real result — `get_evidence()` must return `available: False` instead.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from utils import research_evidence as re_mod


@pytest.fixture(autouse=True)
def _isolated_results_dir(tmp_path, monkeypatch):
    """Every test gets its own empty results directory and a fresh cache,
    so tests can't see each other's files or a stale in-memory report."""
    monkeypatch.setattr(re_mod, "_RESULTS_DIR", tmp_path)
    monkeypatch.setattr(re_mod, "_cache", {"mtime": None, "report": None})
    return tmp_path


def _write_report(tmp_path, overrides=None):
    report = {
        "total_observations": 500,
        "overall_bucket_metrics": {
            "20": {
                "80-89": {
                    "bucket": "80-89",
                    "horizon": 20,
                    "sample_size": 42,
                    "mean_return": 0.031,
                    "median_return": 0.028,
                    "win_rate": 0.62,
                    "benchmark_excess_return": 0.014,
                },
                "<50": {
                    "bucket": "<50",
                    "horizon": 20,
                    "sample_size": 0,
                    "mean_return": None,
                    "median_return": None,
                    "win_rate": None,
                    "benchmark_excess_return": None,
                },
            }
        },
        "regime_bucket_metrics": {
            "Bull": {
                "20": {
                    "80-89": {
                        "bucket": "80-89",
                        "horizon": 20,
                        "sample_size": 5,  # below MIN_REGIME_SAMPLE_SIZE
                        "mean_return": 0.05,
                        "median_return": 0.045,
                        "win_rate": 0.8,
                        "benchmark_excess_return": 0.03,
                    }
                }
            },
            "Strong Bull": {
                "20": {
                    "80-89": {
                        "bucket": "80-89",
                        "horizon": 20,
                        "sample_size": 30,
                        "mean_return": 0.04,
                        "median_return": 0.038,
                        "win_rate": 0.7,
                        "benchmark_excess_return": 0.02,
                    }
                }
            },
        },
        "dataset_version": "abc123deadbeef01",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if overrides:
        report.update(overrides)
    path = tmp_path / re_mod._RESULT_FILENAME
    path.write_text(json.dumps(report))
    return path


# ── valid R2 result ───────────────────────────────────────────────────────


def test_valid_r2_result_is_served(_isolated_results_dir):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=87, horizon=20)

    assert result["available"] is True
    assert result["source"] == "r2"
    assert result["score_bucket"] == "80-89"
    assert result["sample_size"] == 42
    assert result["win_rate"] == 0.62
    assert result["median_forward_return"] == 0.028
    assert result["benchmark_excess_return"] == 0.014
    assert result["dataset_version"] == "abc123deadbeef01"
    assert result["stale"] is False


# ── missing result ────────────────────────────────────────────────────────


def test_missing_result_file_is_reported_honestly(_isolated_results_dir):
    result = re_mod.get_evidence(score=87, horizon=20)

    assert result == {
        "available": False,
        "reason": "no_r2_result",
        "score_bucket": "80-89",
        "horizon": 20,
    }


# ── insufficient sample ───────────────────────────────────────────────────


def test_zero_sample_bucket_is_insufficient(_isolated_results_dir):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=10, horizon=20)  # bucket "<50", sample_size 0

    assert result["available"] is False
    assert result["reason"] == "insufficient_sample"
    assert result["score_bucket"] == "<50"


def test_bucket_absent_from_report_is_insufficient(_isolated_results_dir):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=65, horizon=20)  # "60-69" never written

    assert result["available"] is False
    assert result["reason"] == "insufficient_sample"


# ── stale result ──────────────────────────────────────────────────────────


def test_old_result_is_flagged_stale(_isolated_results_dir):
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    _write_report(_isolated_results_dir, overrides={"generated_at": old_timestamp})

    result = re_mod.get_evidence(score=87, horizon=20)

    assert result["available"] is True
    assert result["stale"] is True


# ── malformed result ──────────────────────────────────────────────────────


def test_malformed_json_fails_closed(_isolated_results_dir):
    path = _isolated_results_dir / re_mod._RESULT_FILENAME
    path.write_text("{not valid json")

    result = re_mod.get_evidence(score=87, horizon=20)

    assert result["available"] is False
    assert result["reason"] == "no_r2_result"


def test_non_object_json_fails_closed(_isolated_results_dir):
    path = _isolated_results_dir / re_mod._RESULT_FILENAME
    path.write_text(json.dumps([1, 2, 3]))

    result = re_mod.get_evidence(score=87, horizon=20)

    assert result["available"] is False
    assert result["reason"] == "no_r2_result"


# ── score at bucket boundary ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected_bucket",
    [
        (49.999, "<50"),
        (50.0, "50-59"),
        (79.999, "70-79"),
        (80.0, "80-89"),
        (89.999, "80-89"),
        (90.0, "90-100"),
        (100.0, "90-100"),
    ],
)
def test_score_bucket_boundaries(_isolated_results_dir, score, expected_bucket):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=score, horizon=20)

    assert result["score_bucket"] == expected_bucket


# ── regime fallback ────────────────────────────────────────────────────────


def test_insufficient_regime_sample_falls_back_to_overall_bucket(_isolated_results_dir):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=87, horizon=20, regime="Bull")  # regime N=5, too small

    assert result["available"] is True
    assert result["regime"] is None  # fell back, not silently labeled Bull
    assert result["sample_size"] == 42  # the overall bucket's sample, not the tiny regime one


def test_sufficient_regime_sample_is_used(_isolated_results_dir):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=87, horizon=20, regime="Strong Bull")  # N=30

    assert result["available"] is True
    assert result["regime"] == "Strong Bull"
    assert result["sample_size"] == 30


def test_unknown_regime_falls_back_to_overall_bucket(_isolated_results_dir):
    _write_report(_isolated_results_dir)

    result = re_mod.get_evidence(score=87, horizon=20, regime="Bear")

    assert result["available"] is True
    assert result["regime"] is None
    assert result["sample_size"] == 42


# ── router: fixture never reachable in production path ────────────────────


def test_router_never_returns_fixture_source(_isolated_results_dir):
    from routers import research_evidence as router_mod

    _write_report(_isolated_results_dir)

    body = asyncio.run(
        router_mod.research_evidence(score=87, horizon=20, regime=None, user={"sub": "someone"})
    )

    assert body["available"] is True
    assert body["source"] == "r2"


def test_router_invalid_horizon_defaults_to_20(_isolated_results_dir):
    from routers import research_evidence as router_mod

    _write_report(_isolated_results_dir)

    body = asyncio.run(
        router_mod.research_evidence(score=87, horizon=17, regime=None, user={"sub": "someone"})
    )

    assert body["horizon"] == 20


def test_router_with_no_result_reports_unavailable_not_error(_isolated_results_dir):
    from routers import research_evidence as router_mod

    body = asyncio.run(
        router_mod.research_evidence(score=87, horizon=20, regime=None, user={"sub": "someone"})
    )

    assert body["available"] is False
    assert "source" not in body
