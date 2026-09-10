# FORTRESS-R3: Feature Correlation and Ablation

FORTRESS-R3 is a read-only research analysis over an R1 SQLite dataset. It
does not import the production scanner or change archived Fortress scores.

## Run

From the repository root:

```bash
PYTHONPATH=.:engine .venv/bin/python -m research.feature_correlation_ablation \
  /path/to/r1-dataset.sqlite \
  --output-dir /path/to/r3-output
```

The command writes:

- `r3_feature_ablation.json`: complete machine-readable report;
- `r3_feature_ablation.md`: compact review report;
- `r3_ablation_table.csv`: individual and group ablation table.

## Evidence requirements

The R1 builder preserves the investigated indicator fields and an optional
`Feature_Contributions` object. Exact score ablation requires a numeric
contribution for every selected feature on every row. If any contribution is
missing, that ablation is marked `unsupported`; the analyzer does not treat a
missing value as zero and does not infer a contribution from correlation.

The current R1 return convention is unadjusted close-to-close return at 5, 10,
20, and 60 exchange sessions. Forward-return comparisons therefore remain
descriptive and are not executable strategy or profitability claims.

## Report sections

- **Correlation:** pairwise Pearson and Spearman relationships using available
  feature pairs only.
- **Contribution diagnostics:** sample size, Pearson/Spearman association with
  the archived score, and univariate R2. These are diagnostics, not fitted
  production weights.
- **Individual ablations:** remove one archived point contribution, recompute
  the bounded counterfactual score, compare score deltas and rank stability,
  and compare top-quintile forward returns.
- **Group ablations:** apply the same operation to related groups:
  trend/momentum, participation/breakout, volatility/VCP, overextension, and
  high proximity.

Correlation is evidence for investigation, not proof that a feature is
redundant. Recommendations must consider missingness, sample sizes, regime
coverage, and forward-return dispersion. Do not remove a feature solely
because it is correlated with another feature.
