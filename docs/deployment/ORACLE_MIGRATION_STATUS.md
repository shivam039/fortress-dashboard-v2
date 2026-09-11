# Oracle Migration Status

**ORACLE_MIGRATION_STATUS: COMPLETE**
**INFRA EPIC STATUS: COMPLETE**

This is the canonical, current-reality doc for Fortress's production
architecture. If any other doc disagrees with this one, this one wins —
correct the other doc, not this one, unless you've independently verified
production has actually changed.

## Canonical production architecture

```
Vercel Production
       ↓
Oracle Production API  (https://api.144.24.107.19.sslip.io — placeholder
                         domain via sslip.io; see "Known limitations" below)
       ↓
Fortress FastAPI  (container: fortress-backend-production)
       ↓
Production Neon
```

- Vercel production env vars `NEXT_PUBLIC_API_URL` and `BACKEND_URL` both
  point to the Oracle production API.
- GitHub Actions production automation (`FORTRESS_BACKEND_URL` /
  `FORTRESS_API_KEY` repo secrets, shared by all backend-targeting
  workflows) points to the Oracle production API.
- Production Neon connectivity confirmed distinct from staging Neon
  (different connection strings; verified by hash comparison, never by
  printing either value).

## Staging architecture (separate, isolated)

```
Oracle staging (container: fortress-backend, https://staging-api.144.24.107.19.sslip.io)
       ↓
Staging Neon (distinct database from production)
```

Production and staging run on the **same Oracle VM** but as fully separate
Docker containers (`fortress-backend-production` vs `fortress-backend`),
each with its own `.env.oracle.{production,staging}` file, own container
name, and own `FORTRESS_ENV` value. Staging's automatic scan schedule is
deliberately scoped to Nifty 50 only; production is configured for all
four universes.

## Shared Caddy design

One Caddy container (`fortress-caddy`) is the sole public entry point on
this VM (ports 80/443) and routes both domains via two site blocks in one
`Caddyfile`:
- `STAGING_API_DOMAIN` → `fortress-backend:8000`
- `PRODUCTION_API_DOMAIN` → `fortress-backend-production:8000`

Both backend containers and Caddy share one external Docker network
(`fortress-shared`). Neither backend container exposes port 8000
publicly — only Caddy's 80/443 are reachable from outside the VM. This
is a deliberate architectural decision (not a compromise) — see
`.agent-room/decisions.md`, "Share one Caddy instance across Oracle
staging and production."

## Orchestration

GitHub Actions remains the sole scheduler/orchestrator for production
automation:

| Workflow | Class | Target |
|---|---|---|
| `auto-scan-eod.yml` (E3, chains E1→T1→E2→maturation) | MUTATING | Oracle production |
| `auto-scan-watchdog.yml` | WATCHDOG (one narrow idempotent recovery case) | Oracle production |
| `bhavcopy-refresh.yml` | DATA_REFRESH | Oracle production |
| `bhavcopy-backfill.yml` (manual only) | DATA_REFRESH | Oracle production |
| `keepalive.yml` | unrelated — pings a legacy Streamlit Cloud app, not this backend | n/a |

All four backend-targeting workflows resolve their target through the
same two repo secrets, so ownership is atomic — there is no separate
per-workflow retargeting to track, and no Oracle-host cron/systemd timer
exists that could duplicate any of this (verified: only stock Ubuntu
maintenance timers run on the VM).

**Note:** E2 (paper-trading automation) is not an independently scheduled
workflow — it executes inside the same `/api/auto-scan/run` pipeline that
E3 triggers, server-side.

## Render status

**Render is not production.** Render is preserved as a **legacy rollback
/ temporary safety net** — fully configured, not deleted, not suspended.
It receives no current production traffic (Vercel and GitHub Actions
both target Oracle exclusively) and is not the target of any active
scheduled mutation.

Render retirement (suspension or deletion) is explicitly **not** part of
migration completion — see `docs/deployment/OPS1_OBSERVATION.md`.

## Rollback procedure (documented, not executed)

If Oracle production experiences a severe issue post-migration:

1. Disable/pause Oracle-targeted production mutation execution as needed
   (e.g. disable the relevant GitHub Actions workflow schedules) to avoid
   any window where both Oracle and Render could mutate production
   simultaneously.
2. Confirm Render's production backend is available/startable.
3. Retarget the GitHub Actions production secrets
   (`FORTRESS_BACKEND_URL`, `FORTRESS_API_KEY`) back to Render's values.
4. Retarget Vercel production env vars (`NEXT_PUBLIC_API_URL`,
   `BACKEND_URL`) back to Render.
5. Redeploy Vercel production.
6. Verify Render health.
7. Verify frontend end-to-end against Render.
8. Verify exactly one scheduler owner is active again (Render, not both).
9. Investigate the Oracle issue separately, out of the rollback's
   critical path.

This order deliberately retargets the scheduler *before* the frontend, so
there is never a window where the frontend points one way and automation
points the other.

## Historical evidence (established during INFRA2-PERF / INFRA3, reused here — not re-run)

- Full four-universe Oracle **staging** scan (Nifty 50 + Next 50 + Midcap
  150 + Smallcap 250, ~500 equities): completed successfully after a
  scan-persistence performance fix. Peak RSS ≈318MB (later runs ≈325MB
  with warm cache), restart count 0.
- A real production scan (Nifty Midcap 150, 160 tickers, manually
  triggered during INFRA3 validation) completed end-to-end on Oracle
  production in 97.3s with 0 restarts, persistence timing matching the
  fix's expected numbers.
- Subsequent real production usage (frontend-triggered Commodities scans,
  MF Lab scans) has continued writing to production Neon without error
  (see current-state DB spot-check below).

## Current-state verification (this pass, non-destructive, no new scans triggered)

- Production API health: `200`, TLS valid.
- Staging API health: `200`, TLS valid.
- Port 8000 directly: unreachable from outside the VM (confirmed — only
  Caddy's 80/443 are public).
- `/api/auto-scan/health`: pipeline `OK`, `universes_configured_correctly:
  true`, all required secret-presence booleans `true`, zero secret values
  in the response.
- Production and staging `DATABASE_URL` values hash to different SHA-256
  digests (confirmed distinct databases without printing either value).
- All three containers (`fortress-backend-production`, `fortress-backend`,
  `fortress-caddy`) report `RestartCount=0` and `Status=running`.
- Zero HTTP 5xx status lines across 744 logged requests in the prior 2
  hours.
- One isolated, already-self-resolved application exception (`pop index
  out of range` in `/api/mf-analysis` during a 903-fund scan, occurred
  once, retried successfully) — a pre-existing MF Lab bug unrelated to
  the Oracle migration, filed as a normal follow-up engineering issue,
  not a migration blocker (see `docs/deployment/OPS1_OBSERVATION.md`
  failure policy).

## Known limitations

- The production API domain is currently `api.<oracle-ip>.sslip.io`
  (a wildcard-DNS convenience domain, same pattern as staging), not a
  purchased custom domain. This is fully functional but cosmetic — a
  real domain can be swapped in later by updating `PRODUCTION_API_DOMAIN`
  and the Vercel/GitHub secrets, with no architecture change required.
- Bhav Copy backfill on production completed during migration closure:
  300/300 requested days processed, 204 trading days covered (2,935
  symbols, 2025-11-17 to 2026-09-11) — just under the ~210 sessions
  needed for full EMA200 coverage on every symbol; the daily
  `bhavcopy-refresh.yml` schedule will close that small remaining gap
  automatically. Not blocking — market data falls back to yfinance for
  any symbol/date still short, same as it did on Render.
- INDstocks provider credentials are currently non-functional in
  production (bad TOTP secret, possibly-expired static token) — the
  system correctly falls back to yfinance per its existing provider
  precedence design. This is a credentials issue to refresh
  operationally, not an architecture issue.

## Superseded documents

`docs/deployment/ORACLE_CUTOVER_PLAN.md` describes the *planned* cutover
and is now historical — the plan it describes has been executed. It is
kept for the procedural detail it recorded, but this document
(`ORACLE_MIGRATION_STATUS.md`) is the current-reality source of truth.
