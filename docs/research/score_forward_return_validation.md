# FORTRESS-R2: Score Forward-Return Validation Methodology & Findings

## 1. Objective and Problem Statement

The goal of **FORTRESS-R2** is to rigorously evaluate whether higher archived Fortress Stock Scores ($S \in [0, 100]$) are statistically and economically associated with superior future equity returns over multiple holding horizons using the point-in-time **R1 Historical Dataset**.

This validation enforces strict empirical discipline:
- **No scoring engine rebuilding or weight curve-fitting:** The analysis strictly uses archived snapshot score outputs (`Score` / `fortress_score`), preserving original regime adjustments and quality-gate outputs.
- **No cherry-picking of time periods:** Every eligible historical snapshot in the R1 dataset is evaluated across all declared market sessions.
- **No selective observation removal:** Losing observations and failed quality setups are preserved in the historical population and never discarded.
- **Explicit distinction among statistical association, predictive value, and tradable strategy evidence.**

---

## 2. Evaluation Schema and Stratifications

### 2.1 Score Buckets
Observations are stratified across five primary test buckets:
- **`50–59`**: Borderline setups ($[50.0, 60.0)$)
- **`60–69`**: Moderate conviction ($[60.0, 70.0)$)
- **`70–79`**: High conviction ($[70.0, 80.0)$)
- **`80–89`**: Institutional conviction ($[80.0, 90.0)$)
- **`90–100`**: Elite / Top-tier conviction ($[90.0, 100.0]$)

Scores below 50 (`<50`) are tracked separately as a negative control / baseline comparison.

### 2.2 Forward Return Horizons
Forward returns are computed at four fixed exchange session horizons ($h \in \{5, 10, 20, 60\}$):
$$\text{Return}(T, h) = \frac{\text{Close}(T + h)}{\text{Close}(T)} - 1$$

Where $T+h$ is the $h$-th trading session following session $T$ on the official exchange calendar. Returns are unadjusted close-to-close percentage returns.

### 2.3 Market Regime Stratification
Observations are evaluated both in aggregate and broken down across the five Fortress market regimes:
1. **Strong Bull**
2. **Bull**
3. **Range**
4. **Caution**
5. **Bear**

---

## 3. Metrics and Statistical Methodology

For each score bucket $B$, horizon $h$, and regime $R$, the engine calculates:

| Metric | Definition | Formula / Interpretation |
| :--- | :--- | :--- |
| **Sample Size ($N$)** | Count of valid labeled observations | Total observations clearing data availability |
| **Mean Return ($\bar{R}$)** | Arithmetic average return | $\frac{1}{N}\sum_{i=1}^N R_i$ |
| **Median Return ($M$)** | 50th percentile of forward return | Robust to outliers and extreme single-stock skew |
| **Win Rate ($W$)** | Percentage of positive returns | $\frac{1}{N}\sum_{i=1}^N \mathbf{1}_{\{R_i > 0\}}$ |
| **Dispersion ($\sigma$, $\text{IQR}$)** | Standard deviation and Interquartile Range | Quantifies outcome variability ($Q_{75} - Q_{25}$) |
| **Negative Return Frequency** | Probability of loss | $\frac{1}{N}\sum_{i=1}^N \mathbf{1}_{\{R_i < 0\}}$ |
| **Benchmark Excess Return** | Return over benchmark / universe | $\bar{R}_{\text{bucket}} - \bar{R}_{\text{benchmark}}$ |
| **Maximum Adverse Excursion (MAE)** | Maximum drawdown from entry during the holding period | $\min_{t \in [1, h]} \frac{\text{Close}(T+t) - \text{Close}(T)}{\text{Close}(T)}$ |

### 3.1 Baselines
- **Universe Baseline:** Equal-weighted mean and median return of all universe members over the same horizon.
- **Benchmark Baseline:** Forward return of the benchmark index (e.g., NIFTY 50) over the identical window.
- **Simple Momentum Baseline:** Forward return of stocks in the top quintile of standard momentum indicators (RSI / RS Score).

---

## 4. Key Interpretive Framework

Research conclusions must explicitly delineate three levels of empirical support:

### Level 1: Association (Correlation)
- Evaluates whether score increases monotonically correspond to higher forward returns ($\bar{R}_{90\text{--}100} > \bar{R}_{80\text{--}89} > \dots > \bar{R}_{50\text{--}59}$).
- Quantified by Spearman rank correlation between score and forward return across the cross-section.
- *Caution:* Association does not guarantee that outperformance survives transaction friction or regime transitions.

### Level 2: Predictive Value (Information Coefficient & Alpha)
- Evaluates whether higher-scored buckets consistently outperform universe and momentum baselines across multiple independent market regimes (e.g. during Range and Caution regimes, not just in Strong Bull).
- Requires positive excess return and consistent win rate advantages above $50\%$.

### Level 3: Tradable Strategy Evidence (Execution & Risk)
- Requires evaluating path risk (MAE) and execution reality:
  1. **Timing Lag:** Fortress scores published at or after market close ($T$) cannot be executed at $T$'s close price; execution occurs at $T+1$ open or later.
  2. **Path Risk / Drawdowns:** A high 60D forward return is not easily tradable if intermediate MAE exceeds $-12\%$ to $-15\%$, triggering stop losses.
  3. **Friction:** Bid-ask spread, impact cost in mid/small caps, and turnover costs must be accounted for before claiming live strategy profitability.

---

## 5. Execution and Reproducibility

The validation engine is implemented as a deterministic standalone CLI and Python module:

```bash
# Run validation on R1 dataset
python -m engine.research.forward_return_validation path/to/dataset.sqlite \
  --benchmark NIFTY \
  --json validation_results.json \
  --markdown validation_report.md
```

All calculations are fully reproducible, audit-traceable to hashed inputs in the R1 dataset archive, and make zero unsupported profitability claims.
