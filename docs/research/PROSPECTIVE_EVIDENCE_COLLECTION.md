# FORTRESS-E1: Prospective Evidence Collection

## Why this exists

FORTRESS-V1 (`docs/research/REAL_VALIDATION_RESULTS.md`) found zero
defensible historical Fortress observations anywhere — legacy scan rows
lack point-in-time provenance, and this environment has no network path to
reconstruct one. E1 does not try to fix the past. It makes every future
real scan a source of genuine, point-in-time, forward-looking evidence, so
Fortress can eventually be judged by real outcomes instead of by nothing.

## Evidence universe

Every successfully scored ticker in a real scan gets a `research_observations`
row — not only ones that became a signal. `signal_ledger` (T1) means SIGNAL;
it is unchanged by this story and still writes exactly what it wrote before.
`research_observations` is a separate, additive table so score buckets can
be compared later without survivorship bias (only recommendations would
silently exclude every ticker Fortress scored but didn't recommend).
Tickers `check_institutional_fortress` returns `None` for (insufficient
history, hard liquidity guard) are unscorable — no entry is built for them;
no score is ever invented.

## Schema

`engine/utils/db.py`, dual-backend (Neon/SQLite) exactly like `signal_ledger`/
`paper_trades`, lazily created on first use:

- **`research_observations`** — `observation_id` (deterministic
  `uuid5(trading_date|symbol|scoring_version)`, so reruns can't drift),
  `scan_id`, `symbol`, `exchange`, `trading_date`, `observation_timestamp`,
  `fortress_score`, `component_scores` (JSON), `market_regime`, `sector`,
  `features_json`, `quality_gate_pass`, `quality_gate_failures`,
  `data_source`, `data_timestamp`, `reference_price`, `scoring_version`,
  `schema_version`, `git_sha`, `passed_criteria`. `UNIQUE(trading_date,
  symbol, scoring_version)`.
- **`research_outcomes`** — `observation_id`, `horizon` (5/10/20/60),
  `status` (`NOT_YET_MATURE` / `MATURED` / `MISSING_DATA`),
  `target_trading_date`, `future_price`, `price_source`, `price_timestamp`,
  `forward_return`, `maturation_timestamp`, `failure_reason`.
  `UNIQUE(observation_id, horizon)`.

## Point-in-time guarantees

`fortress_score`, `component_scores`, `reference_price`, and every other
observation field are exactly what the scan computed at `trading_date` —
never touched again. The same ticker tomorrow is a new row
(`trading_date` differs). The same ticker under a new scoring version is a
new row (`scoring_version` differs). Nothing is ever updated in place on
`research_observations`.

## Versioning

`scoring_version` = `FORTRESS_SCAN_LOGIC_VERSION` (the same version
constant `stock_scanner.logic` already exports — not a new versioning
scheme). `schema_version` = this story's own constant
(`prospective_store.SCHEMA_VERSION`). `git_sha` = best-effort `git
rev-parse HEAD` at collection time, `None` if unavailable (e.g. no `.git`
in a deploy artifact) — never blocks collection.

## Maturation

`prospective_store.mature_pending_outcomes()` reuses R1/R2's own return
definition exactly: `forward_return = unadjusted_close(T+h) /
unadjusted_close(T) - 1`, using `market_data_provider.get_ohlcv()` (the
same function every other part of Fortress uses — never a second market
data path). Session counting uses the *fetched OHLCV series' own trading-day
index*, not calendar-day arithmetic or an invented holiday calendar: if the
base date isn't in the series yet, or the target index doesn't exist yet,
the outcome stays `NOT_YET_MATURE` — it is never calculated early. Once the
target session exists but its close is missing/invalid, or the observation
never had a `reference_price`, the outcome becomes `MISSING_DATA` with a
`failure_reason` — **never a fabricated 0% return**.

Rerunning maturation is safe: `finalize_research_outcome()`'s `UPDATE`
carries `WHERE status = 'NOT_YET_MATURE'`, so an already-`MATURED`/
`MISSING_DATA` row can never be silently rewritten by a later run, even
with a different price series. Any future correction would need a new,
explicit, audited function — none exists today by design.

## Price/corporate-action treatment

Prices are **unadjusted close**, identical to R1's own convention
(`docs/research/historical_dataset.md`). Splits/bonuses/rights issues are
**not** adjusted for — this can make individual labels misleading around a
corporate action, exactly as R1 already documents; this story does not
change or improve on that. No dividend/total-return claim is made anywhere.

## T1/T2 linkage

`research_observations` has no stored foreign key into `signal_ledger` or
`paper_trades` — linkage is a **join on `(scan_id, symbol)`**, chosen
specifically so this story never has to modify T1's or T2's write paths or
return contracts (lower risk, zero redesign). A research observation may
exist with no signal. A signal may be joined back to its observation. A
paper trade still requires its own `signal_id` (T2's existing rule,
unchanged).

## Collection cadence

After market close, per real scan (`engine/main.py`'s `_persist_scan_history`,
next to the existing T1 call): `_record_research_observations()` builds
entries from the full scored `score_df` and calls
`prospective_store.collect_from_scan()`. Maturation is a separate, later
step — run `python -m research.prospective_store mature` daily after
market data updates, independent of any scan.

## Failure handling

If `circuit_breaker_tripped` is true for a scan, `_record_research_observations`
skips entirely and logs why — a provider-outage-truncated scan never
creates observations that would look like valid evidence next to real ones.
This does not change existing `scan_history`/`signal_ledger` persistence
for that scan.

## Sample milestones & status

`python -m research.prospective_store status` reports total observations,
the highest milestone reached (100/250/500/1,000/2,500/5,000), the next
milestone, score-bucket distribution, and matured-`N` per (bucket, horizon)
cell labeled `SUFFICIENT_SAMPLE`/`INSUFFICIENT_SAMPLE` at a floor of 20
(matching the frontend's existing `MIN_EVIDENCE_SAMPLE_SIZE`). A milestone
is a sample-size fact, not a claim that Fortress works.

## R1 export

`python -m research.prospective_store export --output PATH` writes a fresh
SQLite file with exactly the tables `engine/research/forward_return_validation.py`
reads: `metadata`, `sessions`, `observations`, `labels`, `prices`. `runs` is
intentionally omitted — prospective rows have no bundle-selection concept
to record there, and R2's own query never reads it. `metadata` records
`schema_version`, `generated_at`, `scoring_versions` (comma-joined),
`observation_count`. Verified directly in this story: R2
(`run_forward_return_validation`) accepts this export and computes correct
bucket/horizon metrics from it with no changes to R2 itself.

**Known limitation:** `prices` only contains each observation's T0
reference price and each matured horizon's target price — not the full
daily series in between. R2's MAE calculation is best-effort by its own
design ("MAE where available") and will simply find fewer intermediate
points for prospective-sourced data than for a dataset with full daily
price history.

## Validation command

`python -m research.prospective_store validate --output PATH [--benchmark SYM]`
exports R1, and **only** runs R2 if at least one (bucket, horizon) cell has
reached `SUFFICIENT_SAMPLE`; otherwise it reports why R2 was skipped. R2/R3/R4
are never run automatically after a scan or after maturation — only via this
explicit command. Nothing here changes Fortress's production scoring.

## Commands

```bash
# (automatic, inside a real scan — no manual step)
# collection happens in engine/main.py's _persist_scan_history

PYTHONPATH=.:engine .venv/bin/python -m research.prospective_store mature
PYTHONPATH=.:engine .venv/bin/python -m research.prospective_store status
PYTHONPATH=.:engine .venv/bin/python -m research.prospective_store export --output /path/to/r1.sqlite
PYTHONPATH=.:engine .venv/bin/python -m research.prospective_store validate --output /path/to/r1.sqlite --benchmark NIFTY
```

## Global research safety rule

No scoring weight, threshold, feature definition, regime rule, or ranking
semantic was touched by this story. Nothing here uses collected evidence to
change how Fortress scores anything — that must be a separate, hypothesis-driven
experiment with untouched out-of-sample validation, per this story's own
explicit non-goal.
