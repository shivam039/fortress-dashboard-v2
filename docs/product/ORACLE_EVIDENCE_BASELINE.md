# Oracle v1 Evidence Baseline

Status: `NOT_ENOUGH_EVIDENCE`

This is a measurement baseline, not a performance or marketing claim. Oracle
v1 decisions remain deterministic and are not tuned from these observations.

## Current verified operations

- Production deployment: GitHub Actions run `34681409659`, SHA `07cf0ce`.
- Backfill dry-run: run `34681209022`, 50 signals inspected, 0 writes.
- Bounded real backfill and identical repeat: run `34681257886`, both passed.
- Manual maturation after the API-key fix: run `34681554813`, passed.

The backfill output for the 50-signal sample was:

```text
signals_inspected=50
eligible=0
outcomes_to_create=0
writes=0
dry_run=True
```

Because no eligible signals were present in that bounded sample, no valid
production scorecard or horizon distribution can be inferred from it. Counts
for total signals, Oracle decisions, outcome rows, matured/pending/unavailable
rows, decision distribution, and confidence breakdown remain to be captured
from the production ledger through the authenticated reporting path.

## Interpretation and limitations

`NOT_ENOUGH_EVIDENCE` is the required ORACLE4 decision. No accuracy,
probability, win-rate, or predictive-skill claim is justified. A future
baseline must report total rows and the 1/5/20-session maturity distribution,
sampled reference-price and return recomputations, visible exclusions, and a
reproducible decision-by-horizon scorecard.
