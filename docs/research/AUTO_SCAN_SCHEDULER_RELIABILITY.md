# FORTRESS-E3 Scheduler Reliability Patch

Focused reliability patch on top of FORTRESS-E3 (already merged). No
scoring change, no E1/E2/T1/T2 semantic change, no redesign of
`research.auto_scan`.

## Previous failure mode

`.github/workflows/auto-scan-eod.yml` made one `POST /api/auto-scan/run`
call with curl's unbounded defaults. If the Render backend was
sleeping/cold, that request could time out, 502/503, or otherwise fail,
silently losing the day's scheduled evidence run. Even a successful `202`
only proved the request was *accepted* — never that data health passed,
scanning finished, E1/T1/E2/maturation ran, or the run reached a terminal
status, since the workflow never looked at the durable `auto_scan_runs`
record afterward.

## Wake strategy

`GET /api/health` probed before triggering anything: up to 12 attempts,
15s apart (~3 minutes), each with an explicit 10s connect / 30s overall
curl timeout. Fails the workflow with a one-line diagnostic if the
backend never returns `200`.

## Retry strategy (trigger)

`POST /api/auto-scan/run`, up to 5 attempts, 15s apart. Retried only for
transient outcomes: connect failure, `5xx`, `429`. `401`/`403` fail the
workflow immediately (no retry). A `200`/`202` is not accepted as success
by itself — the body must `jq`-parse to a non-empty `run_id`; otherwise
that attempt is treated as a failure and retried like any other
transient case.

## Polling strategy

`GET /api/auto-scan/runs/{run_id}` every 30s, up to 60 times (~30
minutes — sized for a real ~500-symbol scan, not a guess). `RUNNING` (or
any other non-terminal value) keeps polling. `COMPLETE`/`DEGRADED`/
`FAILED` stop the loop immediately.

## Timeout

Hard cap: 60 polls × 30s = 30 minutes. On timeout the workflow fails and
prints the `run_id`, the last known status, and elapsed polling time — it
never assumes the run failed silently or fabricates a status.

## Terminal status handling

- **COMPLETE** — workflow succeeds; prints run_id, trading_date,
  configured/resolved/unresolved universes, unique symbol count,
  observations inserted, signals generated, paper opens/closes,
  circuit-breaker state (only fields actually present in the record).
- **DEGRADED** — workflow **succeeds** (E3 already distinguishes this
  from FAILED — e.g. one configured universe unresolved while the rest
  completed) but prints an explicit warning with the reason. Never
  silently folded into COMPLETE.
- **FAILED** — workflow fails; prints run_id, reason, circuit-breaker
  state, and whatever other compact diagnostic fields are present. No
  secret values in any branch.

## GitHub concurrency behavior

`concurrency: {group: fortress-auto-scan-eod, cancel-in-progress: false}`
— a second scheduled or manual invocation queues rather than running
concurrently, and never cancels an evidence run already in flight (E3's
own idempotency makes a queued rerun safe regardless, but avoiding a
redundant concurrent orchestrator is cleaner). Same pattern applied to
`bhavcopy-refresh.yml` (`fortress-bhavcopy-refresh` group).

`workflow_dispatch` (manual trigger) runs through the identical
wake -> trigger -> poll -> verify steps as the schedule — one code path,
not two.

## Universe configuration requirement

Intended production set (all four, exact `TICKER_GROUPS` names, no
aliases):

```
FORTRESS_AUTO_SCAN_UNIVERSES=Nifty 50,Nifty Next 50,Nifty Midcap 150,Nifty Smallcap 250
```

The code default was **not** changed to this — it stays the conservative
single `"Nifty 50"` universe so an unset env var never silently expands
scope. `research.auto_scan.resolve_configured_universes()` now logs an
operational warning (via `utils.security_config.is_production_environment()`)
when running in production with the env var unset, naming the missing
config and the intended value.

## Tests / checks run

- `python3 -c "import yaml; yaml.safe_load(...)"` — both workflow YAML
  files parse.
- `bash -n` — the extracted shell from both workflows has valid syntax.
- `tests/backend/test_auto_scan_eod_workflow.py` (13 tests, new): YAML/
  concurrency/dispatch shape, bounded retry/poll constants present, no
  `while true`/`until false`, explicit curl timeouts present, no
  `-v`/`--verbose`/`--trace`/echoed-API-key patterns, and the exact `jq`
  extraction logic the workflow uses verified against accepted+run_id,
  missing run_id, empty-string run_id, malformed JSON, and each of
  `COMPLETE`/`DEGRADED`/`FAILED`/`RUNNING`/absent status.
- `tests/backend/test_auto_scan.py` — existing 16 FORTRESS-E3 tests still
  green, plus one new test asserting the production-missing-env warning
  fires.
- Full backend suite: `507 passed` (494 existing + 13 new workflow tests
  from a clean local SQLite test DB).
- No engine scoring/E1/E2/T1/T2 file was modified — only
  `engine/research/auto_scan.py`'s `resolve_configured_universes()`
  gained the operational log line (additive, no behavior change to its
  return value).

## Remaining operational risks

- The wake/trigger/poll logic lives as duplicated shell in two workflow
  files rather than a shared composite action — deliberate, per the
  story's own scope guidance ("keep the duplication simple rather than
  introducing a custom action/package").
- `FORTRESS_AUTO_SCAN_UNIVERSES` still must be set by hand on Render;
  nothing in this patch enforces it beyond the runtime warning — a
  misconfigured production deployment can still silently run on the
  single-universe default (loudly logged, not fatal).
- A ~30 minute poll window assumes a single-worker Render scan job
  completes in that time for ~500 symbols; if the real production
  universe (all four Nifty sets) meaningfully exceeds that duration, the
  poll bound may need revisiting — this was sized from the story's own
  example, not a measured production run.
- GitHub Actions' own scheduled-workflow reliability (a schedule tick can
  be delayed or skipped under GitHub-side load) is outside this patch's
  control, as with any `schedule:`-triggered workflow.
