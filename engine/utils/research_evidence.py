"""engine/utils/research_evidence.py — FORTRESS-V2 read-only loader for real
FORTRESS-R2 forward-return validation results.

This module never runs the research pipeline and never invents a number. It
reads the JSON file produced by `engine.research.forward_return_validation`'s
`--json` output (see docs/research/score_forward_return_validation.md) from a
documented results directory, caches it in memory keyed by file mtime, and
answers "what does real historical evidence say for this score/horizon" —
or reports honestly that no real evidence is available yet.

FORTRESS-V1 found zero real R2 results exist yet (see
docs/research/REAL_VALIDATION_RESULTS.md), so `get_evidence()` currently
always returns `available: False` in every environment — that is the
correct, honest behavior, not a bug. The moment a real result file lands at
`_result_path()`, this module starts serving it with no code change needed.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from research.forward_return_validation import _assign_bucket as assign_score_bucket

# Below this sample size, a regime-specific cut is not statistically useful
# enough to show on its own — fall back to the broader (non-regime) bucket
# rather than presenting a shaky regime number as if it were solid.
MIN_REGIME_SAMPLE_SIZE = 20

# Real R2 evidence older than this is still shown, but flagged `stale` so the
# UI can warn that the market has kept moving since the last validation run.
STALE_AFTER_SECONDS = 30 * 24 * 60 * 60  # 30 days

_RESULTS_DIR = Path(
    os.environ.get(
        "FORTRESS_RESEARCH_RESULTS_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "docs" / "research" / "results"),
    )
)
_RESULT_FILENAME = "r2_validation_report.json"

_cache: Dict[str, Any] = {"mtime": None, "report": None}


def _result_path() -> Path:
    return _RESULTS_DIR / _RESULT_FILENAME


def _load_report() -> Optional[Dict[str, Any]]:
    """Load and cache the latest real R2 report, or None if it doesn't exist
    or is malformed. Malformed content fails closed (treated as unavailable),
    never partially trusted."""
    path = _result_path()
    try:
        stat = path.stat()
    except OSError:
        _cache["mtime"] = None
        _cache["report"] = None
        return None

    if _cache["mtime"] == stat.st_mtime and _cache["report"] is not None:
        return _cache["report"]

    try:
        with path.open("r", encoding="utf-8") as f:
            report = json.load(f)
        if not isinstance(report, dict):
            raise ValueError("R2 result file did not contain a JSON object")
    except (OSError, ValueError, json.JSONDecodeError):
        _cache["mtime"] = None
        _cache["report"] = None
        return None

    _cache["mtime"] = stat.st_mtime
    _cache["report"] = report
    return report


def _unavailable(reason: str, score_bucket: str, horizon: int) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "score_bucket": score_bucket,
        "horizon": horizon,
    }


def get_evidence(score: float, horizon: int, regime: Optional[str] = None) -> Dict[str, Any]:
    """Look up real R2 evidence for a current Fortress score at a given
    forward-return horizon, optionally preferring a regime-specific cut.

    Always returns the same shape. `available: False` means exactly what it
    says — callers (the API router, the frontend) must never substitute
    fixture/illustrative data for a False result.
    """
    score_bucket = assign_score_bucket(score)
    report = _load_report()
    if report is None:
        return _unavailable("no_r2_result", score_bucket, horizon)

    horizon_key = str(horizon)
    regime_used: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None

    if regime:
        regime_metrics = (
            report.get("regime_bucket_metrics", {})
            .get(regime, {})
            .get(horizon_key, {})
            .get(score_bucket)
        )
        if regime_metrics and (regime_metrics.get("sample_size") or 0) >= MIN_REGIME_SAMPLE_SIZE:
            metrics = regime_metrics
            regime_used = regime
        # else: transparently fall through to the broader bucket below —
        # never invent a regime-specific number from an insufficient sample.

    if metrics is None:
        metrics = report.get("overall_bucket_metrics", {}).get(horizon_key, {}).get(score_bucket)

    if not metrics or not (metrics.get("sample_size") or 0):
        return _unavailable("insufficient_sample", score_bucket, horizon)

    generated_at = report.get("generated_at")
    is_stale = False
    if generated_at:
        try:
            import datetime as _dt

            generated_dt = _dt.datetime.fromisoformat(generated_at)
            age_seconds = time.time() - generated_dt.timestamp()
            is_stale = age_seconds > STALE_AFTER_SECONDS
        except (ValueError, TypeError):
            pass

    return {
        "available": True,
        "score_bucket": score_bucket,
        "horizon": horizon,
        "regime": regime_used,
        "sample_size": metrics.get("sample_size"),
        "win_rate": metrics.get("win_rate"),
        "median_forward_return": metrics.get("median_return"),
        "benchmark_excess_return": metrics.get("benchmark_excess_return"),
        "source": "r2",
        "dataset_version": report.get("dataset_version"),
        "generated_at": generated_at,
        "stale": is_stale,
    }
