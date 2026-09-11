# FORTRESS-O1: Production Operations

Makes the automated Fortress evidence pipeline zero-touch: successful runs
require no human action, and failures/degradation/missing runs/stale data
are surfaced so an operator knows exactly when to step in. Detection
only — no scoring change, no E1/E2/E3 semantic change, no second scheduler.

## Automatic schedule

1. **Bhav Copy refresh** — `.github/workflows/bhavcopy-refresh.yml`, 13:30
   and 15:00 UTC weekdays.
2. **E3 evidence run** — `.github/workflows/auto-scan-eod.yml`, 15:45 UTC
   weekdays. Wakes the backend, triggers `/api/auto-scan/run`, polls
   `/api/auto-scan/runs/{run_id}` to a terminal status (~30 min bound).
3. **O1 watchdog** — `.github/workflows/auto-scan-watchdog.yml`, 16:30 UTC
   weekdays (after E3's poll window). Read-only `GET /api/auto-scan/health`
   check; never scans, never writes evidence.

All three are idempotent per trading date and safe to `workflow_dispatch`
manually.

## Expected universes

```
FORTRESS_AUTO_SCAN_UNIVERSES=Nifty 50,Nifty Next 50,Nifty Midcap 150,Nifty Smallcap 250
```

Set on the Render backend service (not in GitHub Actions). `GET
/api/auto-scan/health`'s `production_config.universes_configured_correctly`
reports whether this is set exactly as expected — a boolean only, never
the actual configured value when it's wrong (non-sensitive but avoided as
unnecessary noise). The code default remains the conservative single
`"Nifty 50"` universe if unset (see `AUTOMATED_MULTI_UNIVERSE_SCANNING.md`).

## What COMPLETE / DEGRADED / FAILED mean

- **COMPLETE** — full pipeline ran: data health passed, the four-universe
  union was scored, E1/T1 persisted, E2 managed/opened positions,
  maturation ran. **No human action.**
- **DEGRADED** — the run finished but at least one configured universe
  could not be resolved (the rest completed normally). **Surfaced as a
  GitHub Actions `::warning::` annotation** — the watchdog workflow still
  succeeds; DEGRADED is never treated as COMPLETE.
- **FAILED** — the data-health gate aborted the run, or the scan's own
  circuit breaker tripped. **Surfaced as a failed watchdog run** (GitHub's
  native failure notification) with trading date, run_id, failure reason,
  and circuit-breaker state — never secret values.

## Missing-run detection

A scheduler failure (runner outage, GH Actions incident) can prevent
`/api/auto-scan/run` from ever being called — no `auto_scan_runs` row is
written in that case, so scanning only FAILED rows is insufficient. The
watchdog checks `GET /api/auto-scan/health` for today's trading date:

- No row yet, and it's before ~18:00 UTC → `OK` (not due yet).
- No row after that grace window → `EXPECTED_RUN_MISSING`: the watchdog
  makes **one bounded recovery attempt** (a single `POST
  /api/auto-scan/run` — safe because E3 is idempotent per trading date),
  then still fails the check so it's visibly alerted rather than silently
  "fixed". No retry loop.

## Stale-evidence detection

After a `COMPLETE` run, the health check also flags:
- `observations_inserted == 0` despite a COMPLETE run, or
- Bhav Copy not `"done"` for the trading date when Bhav Copy is the active
  OHLCV source.

This is operational (data plumbing), not a judgment on strategy
performance or scoring outcomes.

## How alerts appear

No new notification infrastructure — GitHub Actions is the alert channel,
per the story's own guidance to avoid a large observability stack:
- `FAILED` / `EXPECTED_RUN_MISSING` / `STALE_EVIDENCE` → the watchdog job
  **fails**, which surfaces in the Actions tab and via GitHub's own
  run-failure notifications (email/GitHub UI, per the repo owner's
  notification settings).
- `DEGRADED` → an `::error::`/`::warning::`-annotated but **successful**
  job — visible in the workflow's summary without failing it.
- `COMPLETE` → silent success, exactly as a zero-touch system should be.

## What requires human intervention

- A failed watchdog run (`FAILED` E3 run, missing run after recovery
  attempt, or stale evidence) — inspect `GET /api/auto-scan/runs/{run_id}`
  or the workflow log for the reason, then decide whether to
  `workflow_dispatch` `auto-scan-eod.yml` again or investigate the
  underlying cause (provider outage, Bhav Copy publish delay, a genuinely
  unresolvable universe name).
- A `DEGRADED` run's warning — usually a configuration issue (an
  unresolved universe name) worth fixing, not urgent.
- `production_config.universes_configured_correctly: false` or any
  `*_set: false` secret flag from `GET /api/auto-scan/health` — a
  deployment configuration gap on Render, fixed by setting the env var
  (see `AUTOMATED_MULTI_UNIVERSE_SCANNING.md`).

## API

`GET /api/auto-scan/health` — `{"pipeline": {...}, "production_config":
{...}}`. Read-only; never fabricates a status; never returns a secret
value (only booleans for secret presence).
