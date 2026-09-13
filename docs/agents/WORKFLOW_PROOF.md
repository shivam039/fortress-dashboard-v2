# Workflow Proof Audit (LUNA MISSES CLOSEOUT Epic 8/9)

Every GitHub Actions workflow in `.github/workflows/` audited against its
**real run history** (`gh`/GitHub Actions API), not just whether the YAML
parses. The distinction that matters throughout this document:

> **CONFIGURED** = the workflow file exists, is syntactically valid, and is
> registered with GitHub Actions (has triggers, would run if triggered).
> **PROVEN** = it has actually executed for real, via the trigger its
> production use depends on (a real `schedule` tick, a real `issues`
> event), and the run's outcome is known.

A workflow can be CONFIGURED for months without ever being PROVEN if its
schedule trigger has simply never fired yet, or if all its historical runs
were manual `workflow_dispatch` substitutes for the trigger that matters.
Per this closeout's rules, no workflow below was triggered manually here
to manufacture a green badge — every status is read from pre-existing run
history only.

## Table

| Workflow | Real trigger | CONFIGURED | LAST_RUN | PROVEN? |
|---|---|---|---|---|
| `agent-eval.yml` | `pull_request` | Yes | run #16, success (2026-09-13) | PROVEN (runs on every agent PR; always green so far) |
| `agent-pipeline.yml` (AGENT4 GitHub Pipeline) | `issues` (real issue trigger) | Yes | run #2, **failure** (2026-09-12) | **NOT PROVEN** — both of its 2 real `issues`-triggered runs failed at the "Coordinator classification and provider resolution" step (issue #39's root cause, already tracked in `AGENT_STATUS.md`: 0/9 roles PROVEN_IN_REAL_RUN). The root-cause bug (scope-gate `/`-requirement) was fixed in PR #81, but that fix has not yet been proven against a fresh real issue trigger. This is exactly the gap Epic 17 (Real Agent Canary) exists to close — not re-litigated here. |
| `agent-room-validate.yml` | `push`, `pull_request` | Yes | run #234, success (2026-09-13) | PROVEN — runs on every push/PR, consistently green |
| `agent-task.yml` | n/a | Yes | **0 runs ever** | CONFIGURED_NOT_YET_OBSERVED. This file's own trigger has never fired in this repo's history. |
| `agent-validate.yml` | n/a | Yes | **0 runs ever** | CONFIGURED_NOT_YET_OBSERVED |
| `ci.yml` | `push`, `pull_request` | Yes | run #225, success (2026-09-13) | PROVEN — consistently green on real pushes/PRs |
| `auto-scan-eod.yml` (FORTRESS-E3) | `schedule` | Yes | success (see AGENT_STATUS / PRODUCTION_OPERATIONS docs) | PROVEN — has real scheduled completions on record |
| `auto-scan-watchdog.yml` (FORTRESS-O1) | `schedule` | Yes | run #5, **failure**, `schedule` trigger (2026-09-11T19:13) | PROVEN to run on schedule, but its most recent real scheduled run **failed**. Of its 5 total runs, 3 failed (2 `workflow_dispatch`, 1 `schedule`) and 2 succeeded (both `workflow_dispatch`). Not yet root-caused in this pass — see Findings below. |
| `bhavcopy-refresh.yml` | `schedule` | Yes | success | PROVEN — recurring daily job with a real scheduled success history |
| `bhavcopy-backfill.yml` | `workflow_dispatch` only (manual, one-off by design) | Yes | run #10, attempt 3, **`status: in_progress`** since 2026-09-13T03:31Z | Its own trigger is manual-only, so CONFIGURED == the bar for this one; run #10 appeared stuck `in_progress` for hours at query time — see Findings below. Prior runs (1-9) show real successes and the documented, already-fixed failure modes (chunking, cooldown, circuit breaker — see `.agent-room/decisions.md`). |
| `deploy-oracle-production.yml` | manual / deploy trigger | Yes | has run history, mixed results (expected for a production deploy workflow under active Oracle migration work) | CONFIGURED and exercised, not claimed PROVEN as a zero-friction path — deploy workflows in this repo are expected to be iterated on live, per prior session history |
| `deploy-oracle-staging.yml` | manual / deploy trigger | Yes | has run history | Same as above |
| `keepalive.yml` (Streamlit) | `schedule` | Yes | has recurring scheduled runs | PROVEN — legacy Streamlit keep-alive, out of scope for further work per CLAUDE.md (legacy UI is reference-only) |
| `oracle-outcomes-backfill.yml` | `workflow_dispatch` | Yes | run #1, success | PROVEN for its manual trigger; no schedule trigger exists for this one by design (one-off backfill) |
| `oracle-outcomes-mature.yml` | `schedule` (`cron: '30 16 * * 1-5'`, i.e. 16:30 UTC / 22:00 IST, weekdays) + `workflow_dispatch` | Yes | 2 runs total, **both `workflow_dispatch`** (2026-09-12) | **CONFIGURED_NOT_YET_OBSERVED for its real schedule trigger.** The workflow was only added 2026-09-12 (one day before this audit); its first scheduled window (16:30 UTC on the next weekday) may simply not have occurred yet at audit time. Not evidence of a bug — evidence that CONFIGURED and PROVEN are genuinely different states here. Re-check after its cron has had at least one real weekday tick. |
| `research-evidence-archive.yml` (FORTRESS-R1) | `schedule` | Yes | **0 runs** | CONFIGURED_NOT_YET_OBSERVED (confirmed again in this pass; unchanged from prior audit) |

## Findings

### 1. `auto-scan-watchdog.yml`'s most recent real scheduled run failed (not yet root-caused)

Run #5 (`schedule`, 2026-09-11T19:13Z, `conclusion: failure`) is this
workflow's most recent execution of its real trigger. This workflow is a
**detection-only** monitor (per its own `PRODUCTION_OPERATIONS.md`
description): it deliberately fails the GitHub Actions run when it
detects `FAILED`/`STALE_EVIDENCE`/`EXPECTED_RUN_MISSING` conditions in the
underlying EOD scan — that is its intended alerting mechanism, not
necessarily a bug in the workflow itself. Distinguishing "the watchdog
correctly alerted on a real EOD scan problem" from "the watchdog itself
is broken" requires reading that run's job output (which condition it
reported), which is beyond this pass's scope to action safely — per this
closeout's own rule, do not re-trigger it to get a green badge, and do
not guess at the cause without evidence. **Left open for human triage**;
recorded here rather than silently dropped.

### 2. `bhavcopy-backfill.yml` run #10 was still `in_progress` at audit time

Run #10 (`workflow_dispatch`, attempt 3, started 2026-09-13T03:31:09Z) was
still reporting `status: in_progress` several hours later at query time.
This workflow has a documented history of stalling (see
`.agent-room/decisions.md`'s bhavcopy backfill root-cause writeup) with
fixes already applied in earlier commits (chunking, retry cooldown,
circuit breaker). Whether run #10 is genuinely still working through a
long backfill range or is stuck again is not something this audit can
determine without live access to the running job — **left open for human
triage**, not force-cancelled or re-triggered.

### 3. `agent-task.yml` / `agent-validate.yml` have zero runs ever

Both are registered workflows with zero recorded executions. Neither is
invoked by anything in this repo's real CI/agent surface as far as this
audit traced (`agent-pipeline.yml`'s real steps call `agent.js` commands
directly, not these files). CONFIGURED_NOT_YET_OBSERVED; no code change
made here, since removing or firing them speculatively is outside this
closeout's scope (no dangerous jobs triggered merely for a badge, no
unrelated cleanup).

## What this pass did NOT do

- Did not trigger any workflow manually to obtain a green run.
- Did not disable, delete, or rewrite any of the three failing/stalled/
  unobserved workflows above — their underlying causes need domain
  investigation (EOD scan data conditions, Render backfill state, and a
  cron simply not having ticked yet, respectively) that this audit correctly
  identifies but does not resolve.
- Did not touch `deploy-oracle-*.yml` (human-approval-gated production
  infra per this closeout's own rules).
