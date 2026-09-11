# OPS1 — Oracle Production Observation

Non-blocking operational follow-up to the Oracle migration (now
COMPLETE — see `docs/deployment/ORACLE_MIGRATION_STATUS.md`). OPS1 is
**not** a prerequisite for AGENT1B or any other work; it runs in
parallel with it.

## Purpose

The migration is closed based on current architecture/health/config
verification plus reused historical scan evidence, per the explicit
decision to separate migration completion from ongoing observation. OPS1
is where the "watch it keep working over time" evidence accumulates,
without blocking anything else on it.

## What to observe (as each naturally occurs — do not manufacture any of it)

- The next scheduled full four-universe E3 run (`auto-scan-eod.yml`) —
  all four universes complete, duration/peak RSS/restart count.
- The watchdog run following that E3 (`auto-scan-watchdog.yml`) —
  targets Oracle, reports correctly.
- The next Bhav Copy refresh (`bhavcopy-refresh.yml`) when due.
- The next legitimate E2/paper-trading lifecycle event, if one occurs —
  read endpoints stay healthy, no duplicate trades, no duplicate E2
  execution.
- Memory/restart stability over time (not just at a single snapshot).
- Caddy stability over time.
- Continued absence of scheduler duplication.
- Continued DB persistence correctness (production vs. staging
  isolation holding up).
- Any unexpected 5xx pattern (as opposed to the isolated, already-known
  MF Lab exception noted in `ORACLE_MIGRATION_STATUS.md`).
- Any material performance regression vs. the known baseline (full
  four-universe: ~300-520s depending on cache warmth, peak RSS
  ~318-325MB, 0 restarts).

## How to observe

Prefer passive evidence: Oracle container logs, `/api/auto-scan/health`,
`/api/bhavcopy/status`, `docker stats`/`docker ps`, and GitHub Actions run
history for the workflows above. Do not manually trigger a full
four-universe scan, E2, a paper trade, or a Bhav Copy backfill merely to
generate OPS1 evidence — observe what actually happens on schedule.

## Failure policy

**SEVERE** (use the documented rollback procedure in
`ORACLE_MIGRATION_STATUS.md`):
- OOM
- crash loop
- DB corruption risk
- duplicate trading mutation
- persistent API outage

**NON-SEVERE** (open a normal engineering issue — do not reopen the
Oracle migration):
- moderate performance regression
- isolated provider failure (e.g. a single INDstocks call failing over
  to yfinance)
- minor operational warning
- an isolated, already-self-resolved exception (e.g. the MF Lab `pop
  index out of range` bug noted at migration closure — track and fix
  through normal engineering process, not through this migration)

A single non-severe finding does not block OPS1 from continuing, and
does not reopen `ORACLE_MIGRATION_STATUS.md`'s COMPLETE status.

## Relationship to Render

OPS1's accumulated evidence is what eventually justifies moving Render
from **LEGACY ROLLBACK** to **SUSPENDED**, and later to **RETIRED**. That
decision belongs to OPS1 (or a dedicated follow-up), not to this
migration-closure story — Render is explicitly not touched here.
