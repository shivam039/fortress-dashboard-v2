# PERF1 findings

Baseline main: `074f0d3`

## Measurement

The safe benchmark uses a deterministic 200-row MF result frame and a fake
Neon connection. It measures the number of remote `execute` calls made by
`upsert_mf_scan_results()` while preserving the production SQL shape.

| Metric | Before | After | Change |
| --- | ---: | ---: | ---: |
| Remote execute calls for 200 rows | 200 | 1 | 99.5% fewer |
| Transaction scope | one per row | one bounded transaction | reduced churn |

The after run completed in 0.005088s against the fake connection. This is not
a production latency claim; real Neon latency was not measured in this safe
run.

## Finding and change

`upsert_mf_scan_results()` used one `_exec()` call per fund on the Neon path.
Because `_exec()` creates a transaction/connection context, a full MF scan
could pay one remote round trip per result. The implementation now uses one
multi-row UPSERT per 200-row chunk inside one transaction. SQLite behavior is
unchanged.

The change does not alter result payloads, conflict keys, scoring, ranking,
provider priority, or failure semantics.

## Other paths inspected

- Equity scans already expose stage duration and RSS telemetry and use bulk
  metadata reads plus bounded metadata concurrency.
- MF scans already bulk-preseed NAV cache and use bounded worker concurrency;
  worker failure evidence remains preserved.
- RSS peak, live provider latency, live Neon latency, and production DB query
  counts: `NOT_MEASURED` (no production workload was triggered).
- MF `pop index out of range` root cause: still unproven.
- No unbounded cache was proven by this pass.

## Validation

- MF/backend focused tests: 22 passed.
- Agent regression suite: 86 passed.
- No deployment or infrastructure change was performed.
