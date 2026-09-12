# Fortress feature reachability (PAPER-AUTO1 audit)

Baseline: `8583007` (audit performed against current `main`).

| Feature | Reachable chain | Status | Evidence / boundary |
|---|---|---|---|
| Dashboard | Vercel `/dashboard` → API client → FastAPI | ACTIVE | `frontend/src/app/dashboard`, `frontend/src/lib/api.ts` |
| Stock Scanner | `/screener` → scan API → scanner service → persisted scan/signal ledger | ACTIVE | read-only UI; scan mutations are explicit user actions |
| Scan History / PRODUCT5 | `/history` → `/api/history/timestamps`, `/data`, `/context` → persisted scans/signals/trades | ACTIVE | historical payloads only; no current Oracle recomputation |
| Oracle v1 | scanner signal or `/api/oracle-decision` → decision service | ON_DEMAND_ACTIVE | decision endpoint is authenticated and does not auto-close trades |
| Paper trading / PRODUCT3-4 | signal → `/api/paper-trades` → persistence → valuation/close/history | ACTIVE | simulation-only; provenance preserved; close is explicit/atomic |
| Automated EOD scan / PAPER-AUTO1 | GitHub Actions `auto-scan-eod` → Oracle API → E3/E2/maturation → durable run | SCHEDULED_ACTIVE | one scheduled owner; zero trades is a valid result |
| Oracle outcomes | signal → outcomes table → maturation workflow → evidence queries | OBSERVATION_WAITING | requires elapsed market horizons; no evidence fabricated |
| Bhav Copy | refresh/backfill workflows → authenticated Oracle API → freshness gate → scanner | SCHEDULED_ACTIVE | weekend/holiday/stale states remain explicit |
| Auto-scan watchdog | scheduled workflow → `/api/auto-scan/health` → bounded recovery | SCHEDULED_ACTIVE | distinguishes failed/stuck/no-run from zero trades |
| MF Lab | `/mf-lab` → MF API/provider → analysis/history | ON_DEMAND_ACTIVE | MF semantics remain separate from stock scans |
| Watchlist | `/watchlist` → authenticated watchlist API → persistence | ON_DEMAND_ACTIVE | bootstrap/error feedback covered by frontend tests |
| QA-AUTO2 | manifest → Playwright fixtures/scenarios → structured evidence | ACTIVE | production mutation blocking and failure injection exist |
| AGENT6 | structured finding → triage → bounded repair → QA/eval/reviewer | ACTIVE | manual approval; no auto-merge/deploy |
| GitHub Issue Sync | actionable finding → fingerprint → create/update issue | ON_DEMAND_ACTIVE | observation-only filtered; issue closure remains human-owned |
| Qwen/qwen_web | experimental provider branch only | INTENTIONALLY_PARKED | `experiment/qwen-dogfood1`; excluded from production paths |
| Render | historical deployment/migration references | ROLLBACK_ONLY | no active workflow/runtime dependency; Oracle workflows use secrets-based backend URL |

## Render audit

Active runtime and scheduler code does not hardcode Render endpoints. Remaining
references are rollback/migration documentation, explanatory historical comments,
or generic English uses of “render”. The workflow comments that previously used
Render examples are treated as stale documentation and should use the neutral
Oracle backend wording; no rollback capability is removed.

## Automated paper path

`auto-scan-eod.yml` calls the configured Oracle backend, which reaches
`/api/auto-scan/run`. `engine/research/auto_scan.py` runs the data-health gate,
scan persistence, signal ledger, Oracle outcome work, and paper policy engine.
The policy engine first manages open simulated positions, then opens only
eligible persisted signals with idempotent policy decisions. Missing price data
leaves positions open. The durable run record exposes opened/closed counts.

No feature in this inventory changes Scanner scoring, Oracle semantics, live
brokerage, or production financial state merely by being present.
