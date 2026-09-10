# Fortress Trade Readiness Review (FORTRESS-V3)

End-to-end verification of the combined system after FORTRESS-V1 (real
research validation) and FORTRESS-V2 (real evidence in the UI). This is a
verification and bug-fixing pass, not new feature work — findings below are
reported, not silently patched, wherever fixing them would exceed that scope.

## Final verdict

## NO-GO

Fortress is not ready for small-live experimentation. This is not primarily
a research-evidence problem (V1 already established that honestly) — it is
that this review found **material integration gaps**: two previously-built
backend capabilities (async scan progress, paper trading) are never wired
into anything a real user can reach, and the market-data circuit breaker
does not detect the exact failure mode (silent empty data, not exceptions)
that a real provider outage would produce. Software correctness within each
component is generally good — the gaps are between components.

## Test results

### Test 1 — Production configuration: **PASS**

Verified live, not just via the existing H3 test suite:

```bash
# Default JWT secret in production → refuses to import
FORTRESS_DB_BACKEND=neon FORTRESS_JWT_SECRET=fortress-dev-jwt-secret-change-in-production-2024 \
  PYTHONPATH=engine .venv/bin/python -c "import auth_utils"
# → RuntimeError: FORTRESS_JWT_SECRET is set to a known default/placeholder value...

# Default admin password in production → refuses to import
FORTRESS_DB_BACKEND=neon FORTRESS_JWT_SECRET=<random> FORTRESS_APP_PASSWORD=fortress123 \
  PYTHONPATH=engine .venv/bin/python -c "import routers.auth"
# → RuntimeError: FORTRESS_APP_PASSWORD is set to a known default/placeholder value...

# Wildcard CORS in production → refuses
FORTRESS_CORS_ORIGINS=* → RuntimeError: ...resolves to a wildcard ('*') origin...

# Fully secure config → boots and serves real requests
FORTRESS_DB_BACKEND=neon, real random JWT secret, real password, explicit CORS origin →
uvicorn started, GET /api/health → 200 OK
```

No secret value appeared in any error output. Development (`FORTRESS_DB_BACKEND=sqlite`)
continues to work with zero configuration, as before.

**Discovered risk (non-blocking for this story, but real):** with
`FORTRESS_DB_BACKEND=neon` and **no** `DATABASE_URL` set, the app does not
fail — `utils.db` logs `Neon unavailable, falling back to SQLite:
DATABASE_URL not found` and continues on local SQLite while still in
"production" security mode. A real deployment that forgets `DATABASE_URL`
gets silent data loss on every restart (ephemeral container storage)
instead of a startup error. H3 deliberately scoped itself to
authentication/CORS secrets, not this — flagging it here as a gap for a
future hardening story, not fixing it in this verification pass.

### Test 2 — Real full-universe scan: **RAN, but reveals a real gap**

Ran the largest available universe, Nifty Smallcap 250 (181 tickers after
resolution), through the actual `/api/scan/jobs` code path against a live
uvicorn instance — not a mock.

| Metric | Value |
| --- | --- |
| Universe size | 181 tickers (Nifty Smallcap 250) |
| Successful tickers | **0** |
| Failed tickers (as reported by the scan) | **0** — see gap below |
| Tickers with no usable price/fundamental data | 181 / 181 (100%) |
| Bhav Copy | Reachable (local cache only) but held no real historical rows for these symbols in this environment |
| INDstocks | Not configured (no credentials in this sandbox) |
| yfinance | 362 connection attempts across two concurrent runs, all rejected (`CONNECT tunnel failed, response 403` — this sandbox's egress policy, not a Fortress bug) |
| Metadata stage duration | 55.5s – 75.8s |
| Market-data stage duration | ~18 min (≈5.5 min stuck in an initial bulk-fetch attempt before falling back, then ≈10s/ticker in per-ticker fallback for all 181) |
| Scoring/indicators duration | included above (interleaved with the per-ticker fallback) |
| Persistence duration | negligible — 0 rows to persist |
| Total wall-clock duration | **~19 minutes** (18:21:39 → 18:40:38) |
| Final job result | `{"results":[],"summary":"No tickers met criteria or market data was unavailable.","scanned":181,"failed":0,"circuit_breaker_tripped":false}` |

This measures Fortress's *failure-handling path* under a total data outage,
not real scan performance — there is no network egress to any market-data
provider in this sandboxed environment (verified directly: NSE, Yahoo
Finance, and INDstocks are all rejected at the proxy level, independent of
any Fortress code). No number above is fabricated; it is what the real code
path actually did.

**Genuine bug found:** `failed` is reported as **0** even though literally
0/181 tickers produced usable data. `engine/main.py`'s circuit breaker
(`_BREAKER_MIN_SAMPLE=10`, `_BREAKER_FAILURE_RATE=0.8`, built in FORTRESS-H2
specifically to "abort... instead of grinding through a likely provider
outage") only increments `scan_failed` when a ticker fetch raises an
exception. When every ticker instead returns silently-empty data (exactly
what a real full provider outage looks like, and exactly what happened
here), no exception is raised, the breaker never sees a failure, and the
scan grinds through all 181 tickers one-by-one over ~19 minutes instead of
aborting early. The final report even says `"circuit_breaker_tripped":false`
and `"failed":0` — actively misleading during precisely the outage scenario
H2 was built to catch quickly. **Not fixed in this pass** (it lives in
`engine/main.py`'s scan loop, unrelated to V1/V2's own changes, and a
correct fix needs to reason about `get_stock_data`'s full empty-vs-error
contract) — flagged as a should-fix-before-live-trading item.

### Test 3 — Async scan UX: **Cannot be verified through the actual UI — it isn't wired up**

The async job API itself works correctly end-to-end (verified directly
against the running server, not the UI):

- `POST /api/scan/jobs` → job created with a `job_id`, `202 Accepted`. ✅
- `GET .../status` → real stage progression observed live: `metadata` →
  `market_data` → `indicators` (with `current`/`total` progress) →
  `completed`. ✅
- A second concurrent job for the same universe was accepted and also
  completed cleanly with no crash or data corruption — the backend
  tolerates concurrent scans. ✅
- `GET .../results` on a completed job returns the same shape a completed
  scan always returns. ✅

**Integration gap found:** `frontend/src/app/screener/page.tsx` — the only
screen with scan controls — **never calls** `scanApi.startScanJob`,
`getScanJobStatus`, or `getScanJobResults`. It exclusively uses the older
synchronous `scanApi.runScan()` (`POST /api/scan`, blocking, 240s client
timeout). A repo-wide search confirms the async job API surface in
`frontend/src/lib/api.ts` (`ScanJobStage`, `ScanJobStatus`, etc.) has zero
callers anywhere in `frontend/src`. FORTRESS-P3 built a complete,
well-tested async scan pipeline that a real user of this product can never
trigger — "refresh reconnects to the job" and "real stage progression
appears" cannot be verified through the actual UI because there is no UI
path to it at all.

What *is* verified at the UI level: the synchronous scan's Run Scan button
is `disabled={loading || !universe || !user}` (`page.tsx:294`), which does
prevent an accidental duplicate submission of the scan users can actually
run.

**Not fixed in this pass** — wiring the screener to the async job API is a
real feature-integration project (new polling logic, job-reconnect-on-reload
handling, a redesigned progress UI), not a "genuine integration regression"
this story's fix-only mandate covers, and the story's own stop condition
rules out feature roadmapping.

### Test 4 — Evidence UI: **Real-data path confirmed, browser session not needed to prove it**

`GET /api/research-evidence?score=87&horizon=20` against the live server
returns `{"available":false,"reason":"no_r2_result","score_bucket":"80-89","horizon":20}`
— exactly V1's finding, served correctly end-to-end, not just in unit tests.
The 16 frontend tests (`frontend/tests/score-evidence.test.mjs`) directly
verify: `HistoricalEvidenceCard` never shows the `ILLUSTRATIVE` badge for a
real (even unavailable) evidence result, never leaks the fixture's numbers,
and correctly shows `MODEL-DERIVED (R2)` for a real result with sample
size, bucket, horizon, and a staleness warning when applicable.

A full browser session was not pursued for this specific test: the
screener's single-stock search (the only place `HistoricalEvidenceCard` is
used) calls `GET /api/scan/search`, which itself requires 210 days of real
price history and correctly 404s with `"Not enough market data for
'RELIANCE.NS'..."` in this network-isolated environment — the same root
blocker as Test 2, verified directly via the API a browser would call. A
browser wouldn't reach the evidence card any differently than this did.

### Test 5 — Signal ledger: **Correct — verified live and by existing tests**

Live: the Test 2 scan above completed with 0 matched tickers, and
`signal_ledger` row count was confirmed **unchanged** (263 before and after)
— correct, because `_record_signal_ledger` in `engine/main.py` only ever
ledgers rows from `results` (institutional-check passes), and building a
ledger entry for a ticker with no real data would be exactly the
fabrication this whole project explicitly forbids. No phantom rows were
written.

Append-only guarantee (a later re-scan must not rewrite an earlier
observation) is directly covered by existing, passing tests —
`test_duplicate_signal_creates_a_new_row_not_an_update` and
`test_re_scored_signal_does_not_touch_the_earlier_row`
(`tests/backend/test_signal_ledger.py`) — since this environment cannot
produce two real scored observations of the same symbol on different real
trading days to demonstrate this from live data.

### Test 6 — Paper trading: **Mechanics correct in isolation, but also unreachable from the product**

All 29 tests in `tests/backend/test_paper_trading_logic.py` and
`test_paper_trading_db.py` pass, directly covering every item in this
test's checklist: signal linkage, entry/stop/target derivation, max
exposure and max simultaneous position limits, deterministic exits (stop
priority over target in the same bar, time-based exit, identical inputs →
identical outputs), P&L computation, and the transaction-cost option.

**Integration gap found, same class as Test 3:** `engine/paper_trading/logic.py`
and its three DB functions (`create_paper_trade`, `close_paper_trade`,
`fetch_paper_trades` in `engine/utils/db.py`) have **no FastAPI router**
anywhere in `engine/routers/`, and **no frontend component or page**
references paper trading at all. FORTRESS-T2 delivered a fully-tested
engine with no product surface — a real user cannot create, view, or close
a single paper position today. Absolutely no real broker execution exists
anywhere in the codebase (confirmed — no order-placement code path touches
paper trading).

**Not fixed in this pass** — building the router and UI is new
feature/integration work.

### Test 7 — Research consistency: **Consistent, trivially**

V1 found zero real R2 results exist. The live API confirms the same:
`available:false` for every score/horizon queried. There is nothing to be
inconsistent between "current scores" and "persisted R2 results" because
no R2 results are persisted. This will become a meaningful test again once
`docs/research/results/r2_validation_report.json` exists.

### Test 8 — Regression: **All green**

```
PYTHONPATH=.:engine .venv/bin/pytest tests/backend -q
430 passed, 4 warnings (pre-existing FastAPI/Starlette deprecation warnings)

npm run test:u2   → 16 passed
npm run test:scan → 7 passed
npm run lint      → clean
tsc --noEmit      → clean
npm run build     → succeeds, all 14 routes prerendered
```

No regressions were introduced by V1/V2. No fix was required in this pass
— every failure mode found above is a pre-existing integration gap, not
something V1/V2/V3 broke.

## Real scan performance (summary)

See Test 2 above. Headline numbers: 181-ticker universe, 0 usable tickers
(100% real-data outage in this sandbox, not a Fortress defect), ~19 minutes
wall-clock, metadata stage ~1 minute, market-data/scoring stage ~18 minutes
dominated by per-ticker fallback retries. The circuit breaker's failure to
recognize this exact scenario (Test 2's genuine bug) means this 19-minute
number would very likely recur on a real production outage, not just here.

## R2/R4 evidence summary

Zero. See `docs/research/REAL_VALIDATION_RESULTS.md` (FORTRESS-V1) for the
full inventory and reasoning: no point-in-time-provenanced historical
Fortress score archive exists, and this class of environment has no network
path to build one. FORTRESS-V2's evidence UI correctly reflects this —
`available:false` everywhere, never a fixture — which this review confirmed
live.

## Production readiness

Security configuration (FORTRESS-H3) is solid and was re-verified live in
this review: production refuses to start on default/missing secrets or a
wildcard CORS origin, and boots cleanly with secure ones. The one open risk
is the silent Neon→SQLite fallback noted in Test 1 — a configuration
mistake (`DATABASE_URL` never set) degrades silently instead of failing
loudly, in a "production" deployment.

## Paper-trading readiness

The trading logic itself (entries, stops, targets, exposure/position
limits, deterministic exits, P&L, cost modeling) is correct and thoroughly
tested. It is not reachable by any user today — there is no API or UI
surface. "Paper trading readiness" is therefore blocked on integration
work, not on the correctness of the trading logic.

## Blockers (must fix before any live/paper rollout decision)

1. **Async scan job UI (P3) is fully unwired** — the screener never uses
   the job-based scan API; only the old synchronous path is reachable.
2. **Paper trading has no API or UI surface (T2)** — the engine exists and
   is tested, but no user can reach it.
3. **Circuit breaker does not detect silent empty-data failures (H2 gap)**
   — a real full-outage scan reports `"failed":0,
   "circuit_breaker_tripped":false"` and takes ~19 minutes instead of
   aborting early, exactly the scenario it was built to catch.
4. **No real research evidence exists** (V1) — R2/R4 evidence is required
   before any live-trading claim, per this story's own acceptance bar.

## Non-blocking issues

1. Silent Neon→SQLite fallback when `DATABASE_URL` is unset in production
   (Test 1) — a configuration-mistake risk, not an immediate blocker.
2. The backend places no limit on concurrent scan jobs per user (two
   identical jobs were accepted back-to-back); the frontend's button-disable
   guard covers the actual UI path, so this is low-severity.
3. This sandboxed environment cannot reach any real market-data provider —
   not a code defect, but it means every number in Test 2 measures failure
   handling, not real-world scan throughput; re-measure in an environment
   with real egress before relying on the ~19-minute figure operationally.

## Reproduction

```bash
# Test 1 (production config)
FORTRESS_DB_BACKEND=neon FORTRESS_JWT_SECRET=fortress-dev-jwt-secret-change-in-production-2024 \
  PYTHONPATH=engine .venv/bin/python -c "import auth_utils"   # must fail
FORTRESS_DB_BACKEND=neon FORTRESS_JWT_SECRET=$(openssl rand -hex 32) FORTRESS_APP_PASSWORD=fortress123 \
  PYTHONPATH=engine .venv/bin/python -c "import routers.auth"  # must fail

# Test 2/3 (real scan + async job API)
cd engine && FORTRESS_DB_BACKEND=neon FORTRESS_JWT_SECRET=$(openssl rand -hex 32) \
  FORTRESS_APP_PASSWORD=<secure> FORTRESS_CORS_ORIGINS=https://app.example.com \
  ../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8099 &
curl -X POST http://127.0.0.1:8099/api/auth/guest -d '{}' -H 'Content-Type: application/json' -c cookies.txt
curl -b cookies.txt -X POST http://127.0.0.1:8099/api/scan/jobs \
  -H 'Content-Type: application/json' -d '{"universe":"Nifty Smallcap 250","portfolio_val":1000000,"risk_pct":0.01}'
curl -b cookies.txt http://127.0.0.1:8099/api/scan/jobs/<job_id>/status   # poll

# Test 3 integration-gap check
grep -rln "startScanJob\|getScanJobStatus" frontend/src   # only lib/api.ts — no callers

# Test 6 integration-gap check
grep -rln "paper_trading\|paper_trade" engine/routers/ frontend/src   # no matches

# Test 8 (regression)
rm -f fortress_history.db
PYTHONPATH=.:engine .venv/bin/pytest tests/backend -q
cd frontend && npm run test:u2 && npm run test:scan && npm run lint && \
  node_modules/.bin/tsc --noEmit -p tsconfig.json && npm run build
```

## Stop condition

This review stops here, as instructed: it reports the integrated verdict
and the fixes required, without opening new feature work or a "Prompt 15"
roadmap. No production Fortress scoring or trading logic was modified.
