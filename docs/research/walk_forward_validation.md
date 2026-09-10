# FORTRESS-R4: Walk-Forward Out-of-Sample Validation

R4 evaluates archived Fortress decisions in chronological rolling windows. It
does not rebuild production scores, tune production weights, or mutate the R1
dataset.

## Run

```bash
PYTHONPATH=.:engine .venv/bin/python -m research.walk_forward_validation \
  /path/to/r1-dataset.sqlite \
  --output-dir /path/to/r4-output \
  --benchmark NIFTY \
  --horizon 5 \
  --top-n 5 10 20
```

Run the command separately for each R1 horizon of interest (`5`, `10`, `20`, or
`60`) when a multi-horizon comparison is required.

The evaluator uses:

- 252 exchange sessions for training;
- 63 sessions for validation;
- 63 untouched sessions for evaluation;
- a 63-session step between windows.

The validation slice is reported but is not used for tuning. Top-N values are
fixed CLI inputs, defaulting to 5, 10, and 20. Within each decision date,
symbols are ranked by archived Fortress score, or archived `RS_Score` for the
simple momentum comparator; ties resolve by symbol ascending. Portfolios are
equal-weighted.

## Outputs

- `r4_walk_forward.json`: complete configuration, windows, metrics, aggregates,
  and limitations;
- `r4_windows.csv`: chronological train/validation/test boundaries and row
  coverage;
- `r4_metrics.csv`: per-window top-N and momentum metrics;
- `r4_walk_forward.md`: human-readable methodology and result summary.

Metrics include sample size, missing-label count, mean/median return, win rate,
benchmark excess return, maximum drawdown, and turnover where a portfolio
selection exists. Score buckets and equal-universe/Nifty baselines are also
reported.

## Leakage and interpretation controls

Window boundaries come only from the declared R1 `sessions` table. A row is
evaluated in the segment containing its observation date; future rows cannot
alter an earlier segment. Missing labels are excluded from that metric's
denominator and remain visible in coverage counts. No forward-fill,
interpolation, or delisting payoff is introduced.

The labels are R1 unadjusted close-to-close descriptive returns. They do not
model next-open execution, slippage, fees, market impact, or capacity.
Therefore R4 results are historical research evidence, not claims of
profitability or live strategy performance. A future experiment that tunes
parameters must define a training-only selection procedure separately rather
than optimizing the full report.
