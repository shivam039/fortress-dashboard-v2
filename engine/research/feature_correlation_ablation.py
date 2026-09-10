"""FORTRESS-R3 feature correlation and ablation analysis.

This module is intentionally separate from the production scanner. It reads an
R1 SQLite dataset, never changes archived scores, and refuses to infer missing
feature contributions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEATURE_GROUPS = {
    "trend_momentum": (
        "EMA_Alignment",
        "Perfect_Alignment",
        "Supertrend_Bullish",
        "ADX_14",
        "RS_Score",
        "RS_Composite",
        "RS_6M",
    ),
    "participation_breakout": (
        "Vol_Surge_Ratio",
        "Breakout_Confirmed",
        "Breakout",
    ),
    "volatility_vcp": ("Is_Coiling", "VCP", "VCP_Coiling"),
    "overextension": (
        "Extension_Pct",
        "EMA200_Extension_Pct",
        "Overextended",
    ),
    "high_proximity": ("Dist_52W_High_Pct",),
}


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2:
        return None
    result = np.corrcoef(np.asarray(left), np.asarray(right))[0, 1]
    return float(result) if math.isfinite(float(result)) else None


def _rank(values: Sequence[float]) -> list[float]:
    return list(pd.Series(values, dtype=float).rank(method="average"))


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2:
        return None
    return _pearson(_rank(left), _rank(right))


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return float(np.mean(values)) if values else None


def _extract_rows(db: sqlite3.Connection) -> pd.DataFrame:
    query = """
        SELECT o.date, o.symbol, o.fortress_score, o.features_json
        FROM observations AS o
        ORDER BY o.date, o.symbol
    """
    rows = db.execute(query).fetchall()
    labels = db.execute(
        "SELECT date, symbol, horizon, forward_return FROM labels WHERE status = 'ok'"
    ).fetchall()
    returns = {}
    for date, symbol, horizon, value in labels:
        returns.setdefault((date, symbol), {})[str(int(horizon))] = _finite(value)
    records: list[dict[str, Any]] = []
    for date, symbol, score, raw_features in rows:
        try:
            features = json.loads(raw_features or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid features_json for {date}/{symbol}") from exc
        if not isinstance(features, dict):
            raise TypeError(f"features_json must be an object for {date}/{symbol}")
        record = {
            "date": date,
            "symbol": symbol,
            "score": _finite(score),
            "forward_returns": returns.get((date, symbol), {}),
            "features": features,
            "contributions": features.get("Feature_Contributions", {}),
        }
        records.append(record)
    if not records:
        return pd.DataFrame(
            columns=["date", "symbol", "score", "features", "contributions", "forward_returns"]
        )
    return pd.DataFrame(records)


def _feature_names(frame: pd.DataFrame) -> list[str]:
    names = set()
    for features in frame["features"]:
        names.update(
            name
            for name, value in features.items()
            if name != "Feature_Contributions" and _finite(value) is not None
        )
    return sorted(names)


def _correlation(frame: pd.DataFrame, features: Sequence[str]) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    for left in features:
        result[left] = {}
        for right in features:
            pairs = [
                (_finite(row["features"].get(left)), _finite(row["features"].get(right)))
                for _, row in frame.iterrows()
            ]
            valid = [(a, b) for a, b in pairs if a is not None and b is not None]
            result[left][right] = _pearson(
                [a for a, _ in valid], [b for _, b in valid]
            )
    return result


def _contribution_metrics(frame: pd.DataFrame, features: Sequence[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for feature in features:
        valid = [
            (_finite(row["features"].get(feature)), row["score"])
            for _, row in frame.iterrows()
        ]
        valid = [(value, score) for value, score in valid if value is not None and score is not None]
        values = [value for value, _ in valid]
        scores = [score for _, score in valid]
        pearson = _pearson(values, scores)
        result[feature] = {
            "sample_size": len(valid),
            "score_pearson": pearson,
            "score_spearman": _spearman(values, scores),
            "univariate_r2": pearson * pearson if pearson is not None else None,
        }
    return result


def _top_quintile(values: Sequence[float]) -> set:
    if not values:
        return set()
    count = max(1, math.ceil(len(values) * 0.2))
    return set(np.argsort(np.asarray(values))[-count:].tolist())


def _forward_impact(
    frame: pd.DataFrame,
    baseline_scores: Sequence[float],
    ablated_scores: Sequence[float],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for horizon in sorted(
        {
            horizon
            for returns in frame["forward_returns"]
            for horizon in returns
        },
        key=int,
    ):
        indices = [
            index
            for index, returns in enumerate(frame["forward_returns"])
            if horizon in returns and returns[horizon] is not None
        ]
        if not indices:
            continue
        base = [baseline_scores[i] for i in indices]
        ablated = [ablated_scores[i] for i in indices]
        returns = [float(frame.iloc[i]["forward_returns"][horizon]) for i in indices]
        base_top = _top_quintile(base)
        ablated_top = _top_quintile(ablated)
        base_mean = _mean(returns[i] for i in base_top)
        ablated_mean = _mean(returns[i] for i in ablated_top)
        result[str(int(horizon))] = {
            "sample_size": len(returns),
            "baseline_top_quintile_size": len(base_top),
            "ablated_top_quintile_size": len(ablated_top),
            "baseline_mean_return": base_mean,
            "ablated_mean_return": ablated_mean,
            "mean_return_delta": (
                ablated_mean - base_mean
                if ablated_mean is not None and base_mean is not None
                else None
            ),
        }
    return result


def _ablation(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    group_name: str | None = None,
) -> dict[str, Any]:
    selected = set(feature_names)
    baseline_rows = frame[frame["score"].notna()].copy()
    baseline_scores = baseline_rows["score"].astype(float).tolist()
    ablated_scores: list[float] = []
    supported = 0
    unsupported = 0
    deltas: list[float] = []
    for _, row in baseline_rows.iterrows():
        contributions = row["contributions"]
        if not isinstance(contributions, Mapping):
            unsupported += 1
            ablated_scores.append(row["score"])
            continue
        values = [_finite(contributions.get(feature)) for feature in selected]
        if any(value is None for value in values):
            unsupported += 1
            ablated_scores.append(row["score"])
            continue
        delta = float(sum(value for value in values if value is not None))
        supported += 1
        deltas.append(delta)
        ablated_scores.append(max(0.0, min(100.0, row["score"] - delta)))

    status = "exact" if unsupported == 0 else "unsupported"
    return {
        "status": status,
        "features": sorted(selected),
        "supported_rows": supported,
        "unsupported_rows": unsupported,
        "score_delta_mean": _mean(-delta for delta in deltas),
        "score_delta_abs_mean": _mean(abs(delta) for delta in deltas),
        "rank_spearman": _spearman(baseline_scores, ablated_scores),
        "rank_changed_count": sum(
            1
            for before, after in zip(_rank(baseline_scores), _rank(ablated_scores))
            if before != after
        ),
        "forward_return_impact": _forward_impact(
            baseline_rows, baseline_scores, ablated_scores
        ),
        "ablation_method": "archived_feature_contributions",
        "group": group_name,
    }


def analyze_dataset(db: sqlite3.Connection) -> dict[str, Any]:
    """Analyze one R1 SQLite dataset without mutating it."""
    frame = _extract_rows(db)
    features = _feature_names(frame) if not frame.empty else []
    individual = {
        feature: _ablation(frame, [feature]) for feature in features
    }
    groups = {}
    for name, candidates in FEATURE_GROUPS.items():
        selected = sorted(set(features).intersection(candidates))
        if selected:
            groups[name] = _ablation(frame, selected, group_name=name)
    return {
        "metadata": {
            "observation_count": (
                int(frame[["date", "symbol"]].drop_duplicates().shape[0])
                if not frame.empty
                else 0
            ),
            "row_count": len(frame),
            "feature_count": len(features),
            "features": features,
            "methodology": "FORTRESS-R3 archived contribution ablation v1",
        },
        "correlation": {
            "pearson": _correlation(frame, features),
            "spearman": {
                left: {
                    right: _spearman(
                        [
                            pair[0]
                            for pair in pairs
                            if pair[0] is not None and pair[1] is not None
                        ],
                        [
                            pair[1]
                            for pair in pairs
                            if pair[0] is not None and pair[1] is not None
                        ],
                    )
                    for right in features
                    for pairs in [[
                        (
                            _finite(row["features"].get(left)),
                            _finite(row["features"].get(right)),
                        )
                        for _, row in frame.iterrows()
                    ]]
                }
                for left in features
            },
        },
        "contributions": _contribution_metrics(frame, features),
        "ablations": {"individual": individual, "groups": groups},
    }


def generate_markdown_report(report: Mapping[str, Any]) -> str:
    """Render a compact, deterministic Markdown report."""
    lines = [
        "# FORTRESS-R3 Feature Correlation and Ablation Report",
        "",
        (
            "Archived scores are unchanged. Exact ablation evidence is used only "
            "when `Feature_Contributions` is present for every row."
        ),
        "",
        "## Metadata",
        "",
        f"- Observations: {report['metadata']['observation_count']}",
        f"- Rows: {report['metadata']['row_count']}",
        f"- Features: {report['metadata']['feature_count']}",
        "",
        "## Contribution diagnostics",
        "",
        "| Feature | N | Score Pearson | Score Spearman | Univariate R2 |",
        "|---|---:|---:|---:|---:|",
    ]
    for feature, metrics in report["contributions"].items():
        lines.append(
            f"| {feature} | {metrics['sample_size']} | "
            f"{metrics['score_pearson']} | {metrics['score_spearman']} | "
            f"{metrics['univariate_r2']} |"
        )
    lines.extend(
        [
            "",
            "## Individual ablations",
            "",
            "| Feature | Status | Supported | Unsupported | Rank Spearman |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for feature, result in report["ablations"]["individual"].items():
        lines.append(
            f"| {feature} | {result['status']} | {result['supported_rows']} | "
            f"{result['unsupported_rows']} | {result['rank_spearman']} |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: Mapping[str, Any], output_dir: Path) -> None:
    """Write JSON, Markdown, and flat ablation CSV artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "r3_feature_ablation.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "r3_feature_ablation.md").write_text(
        generate_markdown_report(report), encoding="utf-8"
    )
    with (output_dir / "r3_ablation_table.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "scope",
                "feature_or_group",
                "status",
                "supported_rows",
                "unsupported_rows",
                "rank_spearman",
                "score_delta_mean",
            ),
        )
        writer.writeheader()
        for scope, values in (
            ("individual", report["ablations"]["individual"]),
            ("group", report["ablations"]["groups"]),
        ):
            for name, result in values.items():
                writer.writerow(
                    {
                        "scope": scope,
                        "feature_or_group": name,
                        "status": result["status"],
                        "supported_rows": result["supported_rows"],
                        "unsupported_rows": result["unsupported_rows"],
                        "rank_spearman": result["rank_spearman"],
                        "score_delta_mean": result["score_delta_mean"],
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.dataset) as db:
        report = analyze_dataset(db)
    write_report(report, args.output_dir)


if __name__ == "__main__":
    main()
