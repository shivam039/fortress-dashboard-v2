"""
engine/research/forward_return_validation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FORTRESS-R2 — Score Forward-Return Validation Engine.

Analyzes historical Fortress scores from the R1 dataset against forward return
labels across multiple horizons (5D, 10D, 20D, 60D) and score buckets
(50-59, 60-69, 70-79, 80-89, 90-100).

Calculates:
  - sample size (N)
  - mean return
  - median return
  - win rate (P(return > 0))
  - dispersion (standard deviation & IQR)
  - negative-return frequency (P(return < 0))
  - benchmark excess return (vs Nifty / benchmark / universe mean)
  - maximum adverse excursion (MAE) where intermediate prices are available

Breaks down performance by market regime:
  - Strong Bull
  - Bull
  - Range
  - Caution
  - Bear

Strictly adheres to research disciplines:
  - No cherry-picking periods.
  - No removal of losing observations.
  - Distinguishes association, predictive value, and tradable strategy evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

SCORE_BUCKETS: List[Tuple[str, float, float]] = [
    ("<50", 0.0, 50.0),
    ("50-59", 50.0, 60.0),
    ("60-69", 60.0, 70.0),
    ("70-79", 70.0, 80.0),
    ("80-89", 80.0, 90.0),
    ("90-100", 90.0, 100.0001),
]

CORE_SCORE_BUCKETS = ["50-59", "60-69", "70-79", "80-89", "90-100"]

HORIZONS: Tuple[int, ...] = (5, 10, 20, 60)

REGIMES: Tuple[str, ...] = ("Strong Bull", "Bull", "Range", "Caution", "Bear")


@dataclass
class BucketHorizonMetrics:
    """Statistical forward return metrics for a specific score bucket and horizon."""
    bucket: str
    horizon: int
    regime: Optional[str] = None
    sample_size: int = 0
    mean_return: Optional[float] = None
    median_return: Optional[float] = None
    win_rate: Optional[float] = None
    std_dev: Optional[float] = None
    iqr: Optional[float] = None
    negative_return_freq: Optional[float] = None
    benchmark_excess_return: Optional[float] = None
    mean_mae: Optional[float] = None
    median_mae: Optional[float] = None
    min_return: Optional[float] = None
    max_return: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket": self.bucket,
            "horizon": self.horizon,
            "regime": self.regime,
            "sample_size": self.sample_size,
            "mean_return": round(self.mean_return, 6) if self.mean_return is not None else None,
            "median_return": round(self.median_return, 6) if self.median_return is not None else None,
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "std_dev": round(self.std_dev, 6) if self.std_dev is not None else None,
            "iqr": round(self.iqr, 6) if self.iqr is not None else None,
            "negative_return_freq": round(self.negative_return_freq, 4) if self.negative_return_freq is not None else None,
            "benchmark_excess_return": round(self.benchmark_excess_return, 6) if self.benchmark_excess_return is not None else None,
            "mean_mae": round(self.mean_mae, 6) if self.mean_mae is not None else None,
            "median_mae": round(self.median_mae, 6) if self.median_mae is not None else None,
            "min_return": round(self.min_return, 6) if self.min_return is not None else None,
            "max_return": round(self.max_return, 6) if self.max_return is not None else None,
        }


@dataclass
class BaselineComparison:
    """Baseline comparisons across horizons."""
    horizon: int
    universe_mean_return: Optional[float] = None
    universe_median_return: Optional[float] = None
    universe_win_rate: Optional[float] = None
    benchmark_mean_return: Optional[float] = None
    top_momentum_mean_return: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon": self.horizon,
            "universe_mean_return": round(self.universe_mean_return, 6) if self.universe_mean_return is not None else None,
            "universe_median_return": round(self.universe_median_return, 6) if self.universe_median_return is not None else None,
            "universe_win_rate": round(self.universe_win_rate, 4) if self.universe_win_rate is not None else None,
            "benchmark_mean_return": round(self.benchmark_mean_return, 6) if self.benchmark_mean_return is not None else None,
            "top_momentum_mean_return": round(self.top_momentum_mean_return, 6) if self.top_momentum_mean_return is not None else None,
        }


@dataclass
class ValidationReport:
    """Comprehensive validation report produced from R1 dataset."""
    total_observations: int
    total_labeled_pairs: int
    horizons: List[int]
    overall_bucket_metrics: Dict[int, Dict[str, BucketHorizonMetrics]]
    regime_bucket_metrics: Dict[str, Dict[int, Dict[str, BucketHorizonMetrics]]]
    baselines: Dict[int, BaselineComparison]
    rank_correlation_by_horizon: Dict[int, float]
    summary_findings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_observations": self.total_observations,
            "total_labeled_pairs": self.total_labeled_pairs,
            "horizons": self.horizons,
            "baselines": {h: b.to_dict() for h, b in self.baselines.items()},
            "overall_bucket_metrics": {
                h: {b: m.to_dict() for b, m in bucket_map.items()}
                for h, bucket_map in self.overall_bucket_metrics.items()
            },
            "regime_bucket_metrics": {
                regime: {
                    h: {b: m.to_dict() for b, m in bucket_map.items()}
                    for h, bucket_map in h_map.items()
                }
                for regime, h_map in self.regime_bucket_metrics.items()
            },
            "rank_correlation_by_horizon": {
                h: round(corr, 4) for h, corr in self.rank_correlation_by_horizon.items()
            },
            "summary_findings": self.summary_findings,
        }


def _assign_bucket(score: Optional[float]) -> str:
    """Assign score to standard bucket."""
    if score is None:
        return "missing"
    for label, low, high in SCORE_BUCKETS:
        if low <= score < high:
            return label
    if score >= 100.0:
        return "90-100"
    return "<50"


def _percentile(values: Sequence[float], p: float) -> float:
    """Calculate percentile from sorted list."""
    if not values:
        raise ValueError("empty sequence")
    k = (len(values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    d0 = values[int(f)] * (c - k)
    d1 = values[int(c)] * (k - f)
    return d0 + d1


def _compute_spearman_rank_correlation(x: List[float], y: List[float]) -> float:
    """Compute Spearman's rank correlation coefficient."""
    n = len(x)
    if n < 3:
        return 0.0

    def get_ranks(seq: List[float]) -> List[float]:
        sorted_indices = sorted(range(n), key=lambda i: seq[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and seq[sorted_indices[j + 1]] == seq[sorted_indices[i]]:
                j += 1
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[sorted_indices[k]] = avg_rank
            i = j + 1
        return ranks

    rank_x = get_ranks(x)
    rank_y = get_ranks(y)

    mean_rx = sum(rank_x) / n
    mean_ry = sum(rank_y) / n

    num = sum((rx - mean_rx) * (ry - mean_ry) for rx, ry in zip(rank_x, rank_y))
    den_x = math.sqrt(sum((rx - mean_rx) ** 2 for rx in rank_x))
    den_y = math.sqrt(sum((ry - mean_ry) ** 2 for ry in rank_y))

    if den_x == 0.0 or den_y == 0.0:
        return 0.0
    return num / (den_x * den_y)


def _compute_stats(
    returns: List[float],
    maes: List[float],
    benchmark_return: Optional[float] = None,
    bucket: str = "",
    horizon: int = 0,
    regime: Optional[str] = None,
) -> BucketHorizonMetrics:
    """Calculate forward return distribution metrics."""
    n = len(returns)
    if n == 0:
        return BucketHorizonMetrics(
            bucket=bucket,
            horizon=horizon,
            regime=regime,
            sample_size=0,
        )

    sorted_returns = sorted(returns)
    mean_ret = sum(returns) / n
    median_ret = _percentile(sorted_returns, 0.5)

    win_count = sum(1 for r in returns if r > 0.0)
    win_rate = win_count / n

    neg_count = sum(1 for r in returns if r < 0.0)
    neg_freq = neg_count / n

    variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    std_dev = math.sqrt(variance)

    q25 = _percentile(sorted_returns, 0.25)
    q75 = _percentile(sorted_returns, 0.75)
    iqr = q75 - q25

    excess_ret = (mean_ret - benchmark_return) if benchmark_return is not None else None

    # MAE stats
    mean_mae = None
    median_mae = None
    if maes:
        mean_mae = sum(maes) / len(maes)
        median_mae = _percentile(sorted(maes), 0.5)

    return BucketHorizonMetrics(
        bucket=bucket,
        horizon=horizon,
        regime=regime,
        sample_size=n,
        mean_return=mean_ret,
        median_return=median_ret,
        win_rate=win_rate,
        std_dev=std_dev,
        iqr=iqr,
        negative_return_freq=neg_freq,
        benchmark_excess_return=excess_ret,
        mean_mae=mean_mae,
        median_mae=median_mae,
        min_return=sorted_returns[0],
        max_return=sorted_returns[-1],
    )


def compute_mae_for_observations(
    conn: sqlite3.Connection,
    obs_list: Sequence[Tuple[str, str, int, str]],  # (date, symbol, horizon, target_date)
) -> Dict[Tuple[str, str, int], float]:
    """Calculate Maximum Adverse Excursion (MAE) for observations using session price series.

    MAE is the minimum percentage return (trough) between session T+1 and T+horizon
    relative to session T's close.
    """
    # Fetch ordered sessions
    sessions_rows = conn.execute("SELECT date FROM sessions ORDER BY date").fetchall()
    session_dates = [r[0] for r in sessions_rows]
    session_idx = {d: i for i, d in enumerate(session_dates)}

    # Group target lookup by symbol
    maes: Dict[Tuple[str, str, int], float] = {}

    # Read prices in bulk for performance
    price_rows = conn.execute("SELECT date, symbol, close FROM prices WHERE close IS NOT NULL").fetchall()
    price_lookup: Dict[Tuple[str, str], float] = {(r[0], r[1]): float(r[2]) for r in price_rows}

    for start_date, symbol, horizon, target_date in obs_list:
        if start_date not in session_idx or target_date not in session_idx:
            continue
        idx_start = session_idx[start_date]
        idx_target = session_idx[target_date]

        p0 = price_lookup.get((start_date, symbol))
        if p0 is None or p0 <= 0:
            continue

        min_price = None
        for i in range(idx_start + 1, idx_target + 1):
            if i < len(session_dates):
                intermediate_date = session_dates[i]
                p_inter = price_lookup.get((intermediate_date, symbol))
                if p_inter is not None:
                    if min_price is None or p_inter < min_price:
                        min_price = p_inter

        if min_price is not None:
            mae = (min_price - p0) / p0
            maes[(start_date, symbol, horizon)] = mae

    return maes


def run_forward_return_validation(
    db_path_or_conn: Union[str, Path, sqlite3.Connection],
    benchmark_symbol: Optional[str] = None,
) -> ValidationReport:
    """Run score forward-return validation against an R1 SQLite dataset.

    Extracts:
      - All scored observations joined with forward return labels.
      - Stratifies by bucket (50-59, 60-69, 70-79, 80-89, 90-100) and horizon (5D, 10D, 20D, 60D).
      - Computes universe baseline and benchmark comparisons.
      - Segregates by market regime (Strong Bull, Bull, Range, Caution, Bear).
      - Computes rank correlation between Score and return.

    Returns:
        ValidationReport dataclass.
    """
    if isinstance(db_path_or_conn, (str, Path)):
        conn = sqlite3.connect(str(db_path_or_conn))
    else:
        conn = db_path_or_conn

    conn.row_factory = sqlite3.Row

    # 1. Total counts
    tot_obs = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    tot_labels = conn.execute("SELECT COUNT(*) FROM labels WHERE forward_return IS NOT NULL").fetchone()[0]

    # 2. Extract joined observations and labels
    query = """
    SELECT 
        o.date, 
        o.symbol, 
        o.fortress_score, 
        o.market_regime, 
        o.features_json,
        l.horizon, 
        l.target_date, 
        l.forward_return
    FROM observations o
    JOIN labels l ON o.date = l.date AND o.symbol = l.symbol
    WHERE l.forward_return IS NOT NULL
      AND o.fortress_score IS NOT NULL
    """
    rows = conn.execute(query).fetchall()

    # Determine benchmark returns per horizon if benchmark symbol exists
    bench_returns_by_horizon: Dict[int, float] = {}
    if benchmark_symbol:
        bench_query = """
        SELECT l.horizon, AVG(l.forward_return) as avg_ret
        FROM labels l
        WHERE l.symbol = ? AND l.forward_return IS NOT NULL
        GROUP BY l.horizon
        """
        for r in conn.execute(bench_query, (benchmark_symbol,)).fetchall():
            bench_returns_by_horizon[int(r["horizon"])] = float(r["avg_ret"])

    # Compute MAE
    obs_for_mae = [
        (r["date"], r["symbol"], int(r["horizon"]), r["target_date"])
        for r in rows
        if r["target_date"] is not None
    ]
    mae_lookup = compute_mae_for_observations(conn, obs_for_mae)

    # 3. Organize data into buckets
    # Structure: by_horizon[h][bucket] = list of returns
    # mae_by_horizon[h][bucket] = list of maes
    by_horizon_bucket: Dict[int, Dict[str, List[float]]] = {h: {b: [] for b, _, _ in SCORE_BUCKETS} for h in HORIZONS}
    mae_by_horizon_bucket: Dict[int, Dict[str, List[float]]] = {h: {b: [] for b, _, _ in SCORE_BUCKETS} for h in HORIZONS}

    # Structure by regime: by_regime[regime][h][bucket] = list of returns
    by_regime_bucket: Dict[str, Dict[int, Dict[str, List[float]]]] = {
        reg: {h: {b: [] for b, _, _ in SCORE_BUCKETS} for h in HORIZONS}
        for reg in REGIMES
    }

    # Universe collections for baselines
    universe_returns_by_h: Dict[int, List[float]] = {h: [] for h in HORIZONS}
    scores_by_h: Dict[int, List[float]] = {h: [] for h in HORIZONS}
    returns_by_h: Dict[int, List[float]] = {h: [] for h in HORIZONS}
    top_momentum_returns_by_h: Dict[int, List[float]] = {h: [] for h in HORIZONS}

    for r in rows:
        h = int(r["horizon"])
        if h not in HORIZONS:
            continue
        ret = float(r["forward_return"])
        score = float(r["fortress_score"])
        bucket = _assign_bucket(score)
        mae = mae_lookup.get((r["date"], r["symbol"], h))

        by_horizon_bucket[h][bucket].append(ret)
        if mae is not None:
            mae_by_horizon_bucket[h][bucket].append(mae)

        universe_returns_by_h[h].append(ret)
        scores_by_h[h].append(score)
        returns_by_h[h].append(ret)

        regime = r["market_regime"]
        if regime in by_regime_bucket:
            by_regime_bucket[regime][h][bucket].append(ret)

        # Simple momentum baseline extract from features_json if available
        features = {}
        if r["features_json"]:
            try:
                features = json.loads(r["features_json"])
            except Exception:
                pass
        rsi = features.get("RSI")
        rs_score = features.get("RS_Score") or features.get("RS_Composite")
        if (rs_score is not None and rs_score >= 80) or (rsi is not None and rsi >= 65):
            top_momentum_returns_by_h[h].append(ret)

    # 4. Compute Baselines
    baselines: Dict[int, BaselineComparison] = {}
    for h in HORIZONS:
        u_rets = universe_returns_by_h[h]
        if u_rets:
            sorted_u = sorted(u_rets)
            u_mean = sum(u_rets) / len(u_rets)
            u_med = _percentile(sorted_u, 0.5)
            u_win = sum(1 for x in u_rets if x > 0) / len(u_rets)
        else:
            u_mean, u_med, u_win = None, None, None

        b_mean = bench_returns_by_horizon.get(h, u_mean)
        mom_rets = top_momentum_returns_by_h[h]
        mom_mean = (sum(mom_rets) / len(mom_rets)) if mom_rets else None

        baselines[h] = BaselineComparison(
            horizon=h,
            universe_mean_return=u_mean,
            universe_median_return=u_med,
            universe_win_rate=u_win,
            benchmark_mean_return=b_mean,
            top_momentum_mean_return=mom_mean,
        )

    # 5. Compute Overall Bucket Metrics
    overall_metrics: Dict[int, Dict[str, BucketHorizonMetrics]] = {}
    rank_correlations: Dict[int, float] = {}

    for h in HORIZONS:
        overall_metrics[h] = {}
        benchmark_mean = baselines[h].benchmark_mean_return

        for label, _, _ in SCORE_BUCKETS:
            rets = by_horizon_bucket[h][label]
            maes = mae_by_horizon_bucket[h][label]
            overall_metrics[h][label] = _compute_stats(
                returns=rets,
                maes=maes,
                benchmark_return=benchmark_mean,
                bucket=label,
                horizon=h,
                regime=None,
            )

        rank_correlations[h] = _compute_spearman_rank_correlation(
            scores_by_h[h], returns_by_h[h]
        )

    # 6. Compute Regime Breakdown Metrics
    regime_metrics: Dict[str, Dict[int, Dict[str, BucketHorizonMetrics]]] = {}
    for regime in REGIMES:
        regime_metrics[regime] = {}
        for h in HORIZONS:
            regime_metrics[regime][h] = {}
            benchmark_mean = baselines[h].benchmark_mean_return
            for label, _, _ in SCORE_BUCKETS:
                rets = by_regime_bucket[regime][h][label]
                regime_metrics[regime][h][label] = _compute_stats(
                    returns=rets,
                    maes=[],
                    benchmark_return=benchmark_mean,
                    bucket=label,
                    horizon=h,
                    regime=regime,
                )

    # 7. Summary findings / observations
    findings: List[str] = []
    for h in HORIZONS:
        b_90 = overall_metrics[h].get("90-100")
        b_50 = overall_metrics[h].get("50-59")
        corr = rank_correlations.get(h, 0.0)
        u_base = baselines[h].universe_mean_return

        if b_90 and b_90.sample_size > 0 and b_50 and b_50.sample_size > 0:
            diff = (b_90.mean_return or 0.0) - (b_50.mean_return or 0.0)
            findings.append(
                f"Horizon {h}D: Score 90-100 mean return = {b_90.mean_return:+.2%} (N={b_90.sample_size}) "
                f"vs Score 50-59 = {b_50.mean_return:+.2%} (N={b_50.sample_size}), "
                f"delta = {diff:+.2%}, Rank Correlation = {corr:+.3f}"
            )
        else:
            findings.append(
                f"Horizon {h}D: Total observations = {len(universe_returns_by_h[h])}, "
                f"Universe mean = {u_base if u_base is not None else 0.0:+.2%}, Rank Correlation = {corr:+.3f}"
            )

    return ValidationReport(
        total_observations=tot_obs,
        total_labeled_pairs=tot_labels,
        horizons=list(HORIZONS),
        overall_bucket_metrics=overall_metrics,
        regime_bucket_metrics=regime_metrics,
        baselines=baselines,
        rank_correlation_by_horizon=rank_correlations,
        summary_findings=findings,
    )


def generate_markdown_report(report: ValidationReport) -> str:
    """Render a structured markdown research report from ValidationReport."""
    lines: List[str] = []
    lines.append("# Fortress Score Forward-Return Validation Report (FORTRESS-R2)\n")
    lines.append(f"**Dataset Summary:** Total observations = `{report.total_observations}`, "
                 f"Total labeled pairs = `{report.total_labeled_pairs}`\n")

    lines.append("## 1. Overall Forward Return Distributions by Score Bucket\n")

    for h in report.horizons:
        lines.append(f"### Horizon: {h} Exchange Sessions ({h}D)\n")
        base = report.baselines.get(h)
        if base:
            lines.append(f"- **Universe Baseline Mean:** `{base.universe_mean_return:+.2%}` | "
                         f"**Median:** `{base.universe_median_return:+.2%}` | "
                         f"**Win Rate:** `{base.universe_win_rate:.1%}`" if base.universe_mean_return is not None else "- **Universe Baseline:** N/A")
            if base.top_momentum_mean_return is not None:
                lines.append(f"- **Top Momentum Baseline Mean:** `{base.top_momentum_mean_return:+.2%}`")
            lines.append(f"- **Spearman Rank Correlation (Score vs Return):** `{report.rank_correlation_by_horizon.get(h, 0.0):+.4f}`\n")

        lines.append("| Bucket | N | Mean Ret | Median Ret | Win Rate | Std Dev | IQR | Neg Freq | Excess Ret | Mean MAE |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

        bucket_map = report.overall_bucket_metrics.get(h, {})
        for label, _, _ in SCORE_BUCKETS:
            m = bucket_map.get(label)
            if not m or m.sample_size == 0:
                lines.append(f"| `{label}` | 0 | — | — | — | — | — | — | — | — |")
                continue
            mean_str = f"{m.mean_return:+.2%}" if m.mean_return is not None else "—"
            med_str = f"{m.median_return:+.2%}" if m.median_return is not None else "—"
            win_str = f"{m.win_rate:.1%}" if m.win_rate is not None else "—"
            std_str = f"{m.std_dev:.2%}" if m.std_dev is not None else "—"
            iqr_str = f"{m.iqr:.2%}" if m.iqr is not None else "—"
            neg_str = f"{m.negative_return_freq:.1%}" if m.negative_return_freq is not None else "—"
            exc_str = f"{m.benchmark_excess_return:+.2%}" if m.benchmark_excess_return is not None else "—"
            mae_str = f"{m.mean_mae:+.2%}" if m.mean_mae is not None else "—"

            lines.append(
                f"| `{label}` | {m.sample_size} | {mean_str} | {med_str} | {win_str} | "
                f"{std_str} | {iqr_str} | {neg_str} | {exc_str} | {mae_str} |"
            )
        lines.append("")

    lines.append("## 2. Market Regime Breakdown\n")
    for regime, h_map in report.regime_bucket_metrics.items():
        lines.append(f"### Regime: {regime}\n")
        lines.append("| Horizon | Bucket | N | Mean Ret | Median Ret | Win Rate | Neg Freq |")
        lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
        has_regime_data = False
        for h in report.horizons:
            bucket_map = h_map.get(h, {})
            for b in CORE_SCORE_BUCKETS:
                m = bucket_map.get(b)
                if m and m.sample_size > 0:
                    has_regime_data = True
                    lines.append(
                        f"| {h}D | `{b}` | {m.sample_size} | {m.mean_return:+.2%} | "
                        f"{m.median_return:+.2%} | {m.win_rate:.1%} | {m.negative_return_freq:.1%} |"
                    )
        if not has_regime_data:
            lines.append("| — | No observations for this regime | 0 | — | — | — | — |")
        lines.append("")

    lines.append("## 3. Research Interpretations & Governance\n")
    lines.append("### Association vs. Predictive Value vs. Tradable Strategy Evidence\n")
    lines.append("1. **Association:** Evaluated via monotonic progression of mean/median returns across buckets (`50-59` through `90-100`) and Spearman rank correlation.")
    lines.append("2. **Predictive Value:** Requires consistency across disparate market regimes and positive excess returns over universe/momentum baselines.")
    lines.append("3. **Tradable Strategy Evidence:** Requires evaluating Maximum Adverse Excursion (MAE), downside tail risk, execution friction, and unadjusted close timing lag.\n")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="FORTRESS-R2: Score forward-return validation.")
    parser.add_argument("dataset", type=Path, help="Path to SQLite R1 dataset")
    parser.add_argument("--benchmark", type=str, default=None, help="Benchmark symbol (e.g. NIFTY)")
    parser.add_argument("--json", type=Path, default=None, help="Path to write JSON validation results")
    parser.add_argument("--markdown", type=Path, default=None, help="Path to write Markdown summary report")
    args = parser.parse_args()

    report = run_forward_return_validation(args.dataset, benchmark_symbol=args.benchmark)
    
    if args.json:
        args.json.write_text(json.dumps(report.to_dict(), indent=2))
        print(f"Wrote JSON results to {args.json}")

    if args.markdown:
        md_content = generate_markdown_report(report)
        args.markdown.write_text(md_content)
        print(f"Wrote Markdown report to {args.markdown}")

    print("\nValidation Summary:")
    for finding in report.summary_findings:
        print("  - " + finding)


if __name__ == "__main__":
    main()
