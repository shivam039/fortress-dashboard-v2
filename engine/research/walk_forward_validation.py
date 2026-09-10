"""FORTRESS-R4 rolling walk-forward out-of-sample validation."""

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

TRAIN_SESSIONS = 252
VALIDATION_SESSIONS = 63
TEST_SESSIONS = 63
STEP_SESSIONS = 63
DEFAULT_TOP_N = (5, 10, 20)
DEFAULT_HORIZON = 5

SCORE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<50", 0.0, 50.0),
    ("50-59", 50.0, 60.0),
    ("60-69", 60.0, 70.0),
    ("70-79", 70.0, 80.0),
    ("80-89", 80.0, 90.0),
    ("90-100", 90.0, 100.0001),
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return float(np.mean(values)) if values else None


def _median(values: Iterable[float]) -> float | None:
    values = list(values)
    return float(np.median(values)) if values else None


def _bucket(score: float | None) -> str | None:
    if score is None:
        return None
    for name, lower, upper in SCORE_BUCKETS:
        if lower <= score < upper:
            return name
    return None


def _drawdown(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return float(worst)


def _metric(returns: Sequence[float], missing_count: int = 0) -> dict[str, Any]:
    values = list(returns)
    return {
        "sample_size": len(values),
        "missing_return_count": missing_count,
        "mean_return": _mean(values),
        "median_return": _median(values),
        "win_rate": (
            sum(value > 0 for value in values) / len(values) if values else None
        ),
        "max_drawdown": _drawdown(values),
    }


def _load_dataset(db: sqlite3.Connection) -> tuple[list[str], list[dict[str, Any]]]:
    sessions = [
        row[0]
        for row in db.execute("SELECT date FROM sessions ORDER BY date").fetchall()
    ]
    labels = {
        (date, symbol, int(horizon)): _number(forward_return)
        for date, symbol, horizon, forward_return, status in db.execute(
            "SELECT date, symbol, horizon, forward_return, status FROM labels"
        )
        if status == "ok"
    }
    records: list[dict[str, Any]] = []
    query = """
        SELECT date, symbol, fortress_score, features_json
        FROM observations
        ORDER BY date, symbol
    """
    for date, symbol, score, features_json in db.execute(query):
        try:
            features = json.loads(features_json or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid features_json for {date}/{symbol}") from exc
        if not isinstance(features, dict):
            raise TypeError(f"features_json must be an object for {date}/{symbol}")
        records.append(
            {
                "date": date,
                "symbol": symbol,
                "score": _number(score),
                "rs_score": _number(features.get("RS_Score")),
                "labels": labels,
            }
        )
    return sessions, records


def _windows(sessions: Sequence[str]) -> list[dict[str, Any]]:
    total = TRAIN_SESSIONS + VALIDATION_SESSIONS + TEST_SESSIONS
    result = []
    start = 0
    while start + total <= len(sessions):
        train = list(sessions[start : start + TRAIN_SESSIONS])
        validation_start = start + TRAIN_SESSIONS
        validation = list(
            sessions[validation_start : validation_start + VALIDATION_SESSIONS]
        )
        test_start = validation_start + VALIDATION_SESSIONS
        test = list(sessions[test_start : test_start + TEST_SESSIONS])
        result.append(
            {
                "index": len(result),
                "train": {"dates": train, "count": len(train)},
                "validation": {"dates": validation, "count": len(validation)},
                "test": {"dates": test, "count": len(test)},
            }
        )
        start += STEP_SESSIONS
    return result


def _add_portfolio_metrics(
    rows: Sequence[dict[str, Any]],
    score_key: str,
    top_n: int,
    horizon: int,
    benchmark_symbol: str,
) -> dict[str, Any]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["symbol"] != benchmark_symbol and row.get(score_key) is not None:
            by_date.setdefault(row["date"], []).append(row)
    returns: list[float] = []
    missing = 0
    previous_symbols: set[str] = set()
    turnovers: list[float] = []
    for date in sorted(by_date):
        selected = sorted(
            by_date[date],
            key=lambda row: (-float(row[score_key]), row["symbol"]),
        )[:top_n]
        selected_symbols = {row["symbol"] for row in selected}
        if previous_symbols:
            turnovers.append(
                len(previous_symbols.symmetric_difference(selected_symbols))
                / max(len(previous_symbols), 1)
            )
        previous_symbols = selected_symbols
        for row in selected:
            value = row["labels"].get((date, row["symbol"], horizon))
            if value is None:
                missing += 1
            else:
                returns.append(value)
    result = _metric(returns, missing)
    result["turnover"] = _mean(turnovers)
    return result


def _equal_universe_metrics(
    rows: Sequence[dict[str, Any]], horizon: int, benchmark_symbol: str
) -> dict[str, Any]:
    by_date: dict[str, list[float]] = {}
    missing = 0
    for row in rows:
        if row["symbol"] == benchmark_symbol or row["score"] is None:
            continue
        value = row["labels"].get((row["date"], row["symbol"], horizon))
        if value is None:
            missing += 1
        else:
            by_date.setdefault(row["date"], []).append(value)
    returns = [_mean(by_date[date]) for date in sorted(by_date)]
    valid_returns = [value for value in returns if value is not None]
    result = _metric(valid_returns, missing)
    result["turnover"] = None
    return result


def _benchmark_metrics(
    rows: Sequence[dict[str, Any]], horizon: int, benchmark_symbol: str
) -> dict[str, Any]:
    returns = []
    missing = 0
    for row in rows:
        if row["symbol"] != benchmark_symbol:
            continue
        value = row["labels"].get((row["date"], row["symbol"], horizon))
        if value is None:
            missing += 1
        else:
            returns.append(value)
    return _metric(returns, missing)


def _benchmark_excess(metric: dict[str, Any], nifty: dict[str, Any]) -> None:
    if metric["mean_return"] is not None and nifty["mean_return"] is not None:
        metric["benchmark_excess_return"] = (
            metric["mean_return"] - nifty["mean_return"]
        )
    else:
        metric["benchmark_excess_return"] = None


def _bucket_metrics(rows: Sequence[dict[str, Any]], horizon: int) -> dict[str, Any]:
    result = {}
    for name, _, _ in SCORE_BUCKETS:
        selected = [row for row in rows if _bucket(row["score"]) == name]
        values = []
        missing = 0
        for row in selected:
            value = row["labels"].get((row["date"], row["symbol"], horizon))
            if value is None:
                missing += 1
            else:
                values.append(value)
        result[name] = _metric(values, missing)
    return result


def _segment_metrics(
    rows: Sequence[dict[str, Any]],
    top_n: Sequence[int],
    horizon: int,
    benchmark_symbol: str,
) -> dict[str, Any]:
    nifty = _benchmark_metrics(rows, horizon, benchmark_symbol)
    metrics: dict[str, Any] = {
        "score_buckets": _bucket_metrics(rows, horizon),
        "top_n": {},
        "momentum_top_n": {},
        "equal_universe": _equal_universe_metrics(
            rows, horizon, benchmark_symbol
        ),
        "nifty": nifty,
    }
    for n in top_n:
        fortress = _add_portfolio_metrics(
            rows, "score", n, horizon, benchmark_symbol
        )
        momentum = _add_portfolio_metrics(
            rows, "rs_score", n, horizon, benchmark_symbol
        )
        _benchmark_excess(fortress, nifty)
        _benchmark_excess(momentum, nifty)
        metrics["top_n"][str(n)] = fortress
        metrics["momentum_top_n"][str(n)] = momentum
    _benchmark_excess(metrics["equal_universe"], nifty)
    for bucket in metrics["score_buckets"].values():
        _benchmark_excess(bucket, nifty)
    return metrics


def _aggregate_metric(metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    returns = [
        metric["mean_return"]
        for metric in metrics
        if metric.get("mean_return") is not None
    ]
    sample_size = sum(metric.get("sample_size", 0) for metric in metrics)
    wins = [
        metric["win_rate"] * metric["sample_size"]
        for metric in metrics
        if metric.get("win_rate") is not None
    ]
    result = {
        "sample_size": sample_size,
        "window_count": len(metrics),
        "mean_return": _mean(returns),
        "win_rate": sum(wins) / sample_size if sample_size else None,
        "max_drawdown": min(
            (metric["max_drawdown"] for metric in metrics if metric["max_drawdown"] is not None),
            default=None,
        ),
    }
    return result


def analyze_dataset(
    db: sqlite3.Connection,
    *,
    top_n: Sequence[int] = DEFAULT_TOP_N,
    horizon: int = DEFAULT_HORIZON,
    benchmark_symbol: str = "NIFTY",
) -> dict[str, Any]:
    """Evaluate fixed archived signals in rolling train/validation/test windows."""
    top_n = tuple(sorted({int(value) for value in top_n if int(value) > 0}))
    if not top_n:
        raise ValueError("top_n must contain at least one positive value")
    sessions, records = _load_dataset(db)
    windows = _windows(sessions)
    for window in windows:
        window_metrics: dict[str, Any] = {}
        for segment in ("train", "validation", "test"):
            dates = set(window[segment]["dates"])
            rows = [row for row in records if row["date"] in dates]
            window_metrics[segment] = _segment_metrics(
                rows, top_n, horizon, benchmark_symbol
            )
            window[segment]["metrics"] = window_metrics[segment]
            window[segment]["rows"] = len(rows)
            window[segment]["benchmark_symbol"] = benchmark_symbol
        window["metrics"] = window_metrics
    aggregate: dict[str, Any] = {"top_n": {}}
    for n in top_n:
        train_metrics = [
            window["train"]["metrics"]["top_n"][str(n)] for window in windows
        ] + [
            window["validation"]["metrics"]["top_n"][str(n)] for window in windows
        ]
        test_metrics = [
            window["test"]["metrics"]["top_n"][str(n)] for window in windows
        ]
        in_sample = _aggregate_metric(train_metrics)
        out_of_sample = _aggregate_metric(test_metrics)
        aggregate["top_n"][str(n)] = {
            "in_sample": in_sample,
            "out_of_sample": out_of_sample,
            "degradation": (
                out_of_sample["mean_return"] - in_sample["mean_return"]
                if out_of_sample["mean_return"] is not None
                and in_sample["mean_return"] is not None
                else None
            ),
        }
    return {
        "configuration": {
            "train_sessions": TRAIN_SESSIONS,
            "validation_sessions": VALIDATION_SESSIONS,
            "test_sessions": TEST_SESSIONS,
            "step_sessions": STEP_SESSIONS,
            "horizon": horizon,
            "top_n": list(top_n),
            "benchmark_symbol": benchmark_symbol,
            "validation_used_for_tuning": False,
            "selection_rule": "descending signal, symbol ascending tie-break",
        },
        "windows": windows,
        "aggregate": aggregate,
        "limitations": [
            "Uses archived close-to-close R1 labels and does not model execution costs.",
            "Validation is reported but no parameter tuning is performed.",
            "Missing labels are excluded from metric denominators and reported.",
            "Results are descriptive research evidence, not profitability claims.",
        ],
    }


def generate_markdown_report(report: Mapping[str, Any]) -> str:
    """Render a deterministic R4 methodology and results summary."""
    config = report["configuration"]
    lines = [
        "# FORTRESS-R4 Walk-Forward Out-of-Sample Validation",
        "",
        "## Methodology",
        "",
        f"- Training window: {config['train_sessions']} sessions",
        f"- Validation window: {config['validation_sessions']} sessions",
        f"- Untouched evaluation period: {config['test_sessions']} sessions",
        f"- Step size: {config['step_sessions']} sessions",
        f"- Validation used for tuning: {config['validation_used_for_tuning']}",
        "",
        "## In-sample and out-of-sample performance",
        "",
        "| N | In-sample mean | Out-of-sample mean | Degradation |",
        "|---:|---:|---:|---:|",
    ]
    for n in config["top_n"]:
        result = report["aggregate"]["top_n"][str(n)]
        lines.append(
            f"| {n} | {result['in_sample']['mean_return']} | "
            f"{result['out_of_sample']['mean_return']} | {result['degradation']} |"
        )
    lines.extend(
        [
            "",
            "## Stability and limitations",
            "",
            f"- Windows evaluated: {len(report['windows'])}",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def write_report(report: Mapping[str, Any], output_dir: Path) -> None:
    """Write deterministic JSON, window CSV, metric CSV, and Markdown files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "r4_walk_forward.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "r4_walk_forward.md").write_text(
        generate_markdown_report(report), encoding="utf-8"
    )
    with (output_dir / "r4_windows.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["window", "segment", "start", "end", "session_count", "row_count"]
        )
        for window in report["windows"]:
            for segment in ("train", "validation", "test"):
                value = window[segment]
                writer.writerow(
                    [
                        window["index"],
                        segment,
                        value["dates"][0],
                        value["dates"][-1],
                        value["count"],
                        value["rows"],
                    ]
                )
    with (output_dir / "r4_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["window", "segment", "strategy", "n", "sample_size", "mean_return", "win_rate", "max_drawdown"]
        )
        for window in report["windows"]:
            for segment in ("train", "validation", "test"):
                metrics = window[segment]["metrics"]
                for strategy in ("top_n", "momentum_top_n"):
                    for n, metric in metrics[strategy].items():
                        writer.writerow(
                            [
                                window["index"],
                                segment,
                                strategy,
                                n,
                                metric["sample_size"],
                                metric["mean_return"],
                                metric["win_rate"],
                                metric["max_drawdown"],
                            ]
                        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--benchmark", default="NIFTY")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--top-n", nargs="+", type=int, default=list(DEFAULT_TOP_N))
    args = parser.parse_args()
    with sqlite3.connect(args.dataset) as db:
        report = analyze_dataset(
            db,
            top_n=args.top_n,
            horizon=args.horizon,
            benchmark_symbol=args.benchmark,
        )
    write_report(report, args.output_dir)


if __name__ == "__main__":
    main()
