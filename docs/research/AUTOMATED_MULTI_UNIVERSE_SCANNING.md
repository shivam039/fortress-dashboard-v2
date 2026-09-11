# FORTRESS-E3: Automated Multi-Universe EOD Scanning

Removes manual scan initiation from prospective evidence collection.
Orchestrates T1/E1/T2/E2 exactly as they already exist — no scoring
change, no new trading logic.

## Pipeline

```
MARKET CLOSE -> VERIFY DATA HEALTH -> RESOLVE CONFIGURED UNIVERSES ->
BUILD UNIQUE SYMBOL UNION -> SCORE EACH SYMBOL ONCE -> RECORD UNIVERSE
MEMBERSHIP -> E1 RESEARCH OBSERVATIONS -> T1 QUALIFYING SIGNALS ->
E2 PAPER PORTFOLIO -> MATURE PREVIOUS E1 OUTCOMES -> DAILY SUMMARY
```

Implemented in `engine/research/auto_scan.py:run_daily_auto_scan()`.

## Universe configuration

`FORTRESS_AUTO_SCAN_UNIVERSES` — comma-separated names matching
`fortress_config.TICKER_GROUPS` keys (e.g. `"Nifty 50,Nifty 100"`). Unset
or empty resolves to the explicit, conservative
`DEFAULT_AUTO_SCAN_UNIVERSES = ("Nifty 50",)` — never silently "everything".

## Overlap deduplication

`build_symbol_union()` resolves every configured universe's membership
first, then unions to unique symbols (`RELIANCE.NS` in 4 overlapping
indices still appears once). The union is scored in **one** call to
`main.execute_scan(req, tickers_override=union, ...)` — not one scan per
universe — so a symbol in 4 configured universes is scored exactly once.

Per-symbol universe membership is recorded separately in the new
`symbol_universe_membership` table (`trading_date, symbol, universe`,
`UNIQUE` on all three, idempotent upsert-free insert-or-ignore). This is
contextual metadata only: `research_observations` keeps its existing
FORTRESS-E1 identity — `UNIQUE(trading_date, symbol, scoring_version)` —
completely untouched, so overlap can never produce more than one
observation per symbol per day regardless of how many universes list it.

One subtlety this preserves exactly: `check_institutional_fortress`'s
`selected_universe == "Nifty Smallcap 250"` liquidity guard is
universe-specific scoring behavior. A combined multi-universe scan passes
one synthetic label (`AUTO_MULTI(...)`) as `req.universe`, which would
otherwise silently disable that guard for every smallcap symbol. `execute_scan`
gained an optional `universe_membership` map so each symbol's real
membership (not the synthetic batch label) reaches `check_institutional_fortress`
when it matters — the only such universe-conditional rule in the scanner.

## Data-health gate

`check_data_health()` runs **before** any scan, reusing existing signals
(no new health-check subsystem):

- **Bhav Copy freshness** — `utils.db.get_bhavcopy_fetch_status(trading_date)`
  must be `"done"`, checked only when Bhav Copy is the active OHLCV source
  (`market_data_provider.provider_status()["ohlcv_source"]`).
- **Provider availability** — the same `provider_status()` call.
- **Expected universe resolution** — which configured names actually exist
  in `TICKER_GROUPS`; none resolving is fatal.
- **Required history depth** — a canary OHLCV fetch (first symbol of the
  first resolvable universe) must return >=210 rows, the same bar
  `execute_scan`'s own circuit breaker already enforces.

Any issue -> `healthy: False` -> the run **aborts before scanning**: no
scan, no signal_ledger rows, no research_observations, run status
`FAILED` with the reason recorded. An unresolved (but not the only)
universe is reported (`unresolved_universes`) without failing the run —
it marks the run `DEGRADED` instead once scanning completes.

The scanner's own existing circuit breaker (a mid-scan provider outage)
is a separate, already-tested protection; if it trips, the run is also
marked `FAILED` and no new paper positions are opened from it (existing
open positions are still managed/exited).

## Scheduling

Uses the repository's existing HTTP-call-cron pattern
(`.github/workflows/bhavcopy-refresh.yml`), not a second scheduler:
`.github/workflows/auto-scan-eod.yml` runs at 15:45 UTC (21:15 IST)
weekdays — after both scheduled Bhav Copy refresh attempts — and POSTs to
`/api/auto-scan/run` on the deployed backend.

## API

- `POST /api/auto-scan/run` — fire-and-forget (matches `/api/bhavcopy/refresh`'s
  `BackgroundTasks` convention; a multi-universe scan is long-running work
  per `engine/CLAUDE.md`'s "never block a request > 5s" rule). Returns
  `{"run_id": ..., "status": "accepted"}` immediately.
- `GET /api/auto-scan/status` — the latest run's full record (never
  fabricates; `{"status": "NO_RUNS_YET"}` if none exists).
- `GET /api/auto-scan/runs/{run_id}` — one run's full audit record.

## Idempotency

Rerunning the scheduled job for the same `trading_date`:

- **Scan/E1/T1**: `auto_scan_runs` is checked for a prior `COMPLETE` run for
  that `trading_date` — if found, the scan is skipped entirely (never
  re-scored, never duplicated) and the summary reuses the prior run's
  counts rather than fabricating new ones (`successfully_scored`/
  `unscorable` report `null`, not `0`, on a skipped rerun).
- **E2**: already idempotent (FORTRESS-E2's `signal_id`-keyed
  `paper_policy_decisions` upsert) — always re-runs safely.
- **Maturation**: already idempotent (only touches `NOT_YET_MATURE` rows) —
  always re-runs safely.
- **Membership**: `symbol_universe_membership`'s `UNIQUE(trading_date,
  symbol, universe)` makes `record_universe_memberships()` a safe
  insert-or-ignore on rerun.

Every invocation still gets its own durable `run_id` row for audit,
whether or not it actually re-scanned.

## Run audit trail (`auto_scan_runs`)

One row per invocation: `run_id`, `trading_date`, `status`
(`RUNNING`/`COMPLETE`/`DEGRADED`/`FAILED`), `configured_universes`,
`resolved_universes`, `unresolved_universes`, `unique_symbol_count`,
`membership_count`, `started_at`, `completed_at`, `provider_health`,
`scoring_version`, `git_sha`, `observations_inserted`,
`signals_generated`, `paper_opened`, `paper_closed`,
`circuit_breaker_tripped`, `reason`, `summary_json`.

Full chain: `paper_trade -> signal_ledger row -> (scan_id, symbol) ->
research_observations row -> scoring_version`, plus (new) `symbol ->
symbol_universe_membership rows -> auto_scan_runs.run_id` for which
automated run and which configured universes produced it.

## Daily summary

```json
{
  "run_id": "...", "trading_date": "2026-09-11", "configured_universes": 6,
  "unique_symbols": 487, "successfully_scored": 471, "unscorable": 16,
  "research_observations_inserted": 471, "signals_generated": 23,
  "paper_positions_opened": 6, "paper_positions_closed": 2,
  "outcomes_matured": {"checked": 940, "matured": 418, "unavailable": 3,
                         "matured_by_horizon": {"5": 418, "10": 402, "20": 365, "60": 211}},
  "circuit_breaker": "not_triggered", "data_health": "healthy",
  "run_status": "COMPLETE"
}
```

Every field comes straight from the DB/scan result — a skipped rerun or a
failed/degraded run reports `null`/`0` for whatever genuinely wasn't
computed rather than inventing a plausible-looking number.

## How to run

```bash
# Manually, once:
PYTHONPATH=.:engine .venv/bin/python -m research.auto_scan --trading-date 2026-09-11

# Or trigger the deployed backend the same way the scheduled workflow does:
curl -X POST https://<backend>/api/auto-scan/run -H "X-API-Key: $FORTRESS_API_KEY" -d '{}'
```

## Files changed

- `engine/main.py` — `execute_scan()` gained `tickers_override`, `run_meta`
  (an internal-bookkeeping out-param), and `universe_membership` (all
  optional, `None` by default — zero behavior change for every existing
  caller: `/api/scan`, `/api/scan/jobs`).
- `engine/research/prospective_store.py` — `mature_pending_outcomes()`
  additionally returns `matured_by_horizon` (existing keys unchanged).
- `engine/utils/db.py` — `auto_scan_runs` and `symbol_universe_membership`
  tables + accessors.
- `engine/research/auto_scan.py` (new) — the orchestrator.
- `engine/routers/auto_scan.py` (new) — the HTTP trigger/status surface.
- `.github/workflows/auto-scan-eod.yml` (new) — the daily schedule.
- `tests/backend/test_auto_scan.py` (new) — 16 tests.

`engine/stock_scanner/logic.py` (scoring), `engine/paper_trading/logic.py`
(T2), and `engine/paper_trading/policy_engine.py` (E2) are unchanged.
