# Fortress Trade Readiness Review V4

Closes the four concrete integration blockers FORTRESS-V3 found. This is a
fix-only story on top of FORTRESS-E1 (already merged) — no scoring change,
no new features beyond the smallest usable paper-trading surface the
blocker explicitly asked for.

## V3 blockers and fixes

### Blocker A — async scans were never wired into the screener

**Fix:** `frontend/src/app/screener/page.tsx`'s Run Scan button now calls
`scanApi.startScanJob()` → polls `getScanJobStatus()` every 2s → calls
`getScanJobResults()` on completion. `frontend/src/lib/scan-state.ts` gained
`jobId`/`stage`/`progress` fields and `startJob`/`updateJobStatus`/
`completeJob`/`failJob` methods. `ScanStatus.tsx` now renders the real
server-reported stage and `current/total` ticker count — never a
percentage. `jobId` persists to `sessionStorage`; a refresh with a still-
running job resumes polling the same job instead of showing "unknown" or
starting a new one (`store.restore()` now only degrades a running state to
`unknown` when there's no `jobId` to reconnect to). `runScan()` guards on
`scan.status === 'running'` before submitting, and the button stays
`disabled` while running — no duplicate submissions. The old synchronous
`POST /api/scan` endpoint and `scanApi.runScanDetailed()`/`store.start()`
are untouched for any other caller.

**Files:** `frontend/src/lib/scan-state.ts`, `frontend/src/app/screener/page.tsx`,
`frontend/src/components/ScanStatus.tsx`, `frontend/tests/scan.test.mjs`.

### Blocker B — silent empty-data circuit-breaker bug

**Fix:** `engine/main.py`'s `_record_result()` now classifies `hist is
None or hist.empty or len(hist) < 210` as an evaluation failure *before*
calling `check_institutional_fortress` — previously this silently skipped
scoring with no failure counted at all. A ticker with real, sufficient
data that `check_institutional_fortress` still legitimately rejects (e.g.
the smallcap liquidity guard) is never touched — that function itself was
not modified. The trip-check was factored into one shared
`_maybe_trip_breaker()` used by both the batch and per-ticker-fallback
paths, so the threshold (`_BREAKER_MIN_SAMPLE=10`, `_BREAKER_FAILURE_RATE=0.8`
— unchanged, no evidence required correcting it) is evaluated identically
everywhere. `_persist_scan_history` was also split into three independent
try/except blocks (scan_history, signal ledger, research observations) so
a legacy `scan_history_details` persistence failure can no longer silently
prevent T1/E1 writes for an otherwise-successful scan — a real gap this
work surfaced while adding regression coverage.

**Files:** `engine/main.py`, `tests/backend/test_circuit_breaker_empty_data.py`
(new), `tests/backend/test_api.py` and `tests/backend/test_scan_jobs_api.py`
(two pre-existing tests corrected — they asserted the *old, buggy*
all-empty-data behavior as if it were correct; fixed to use real per-ticker
data so they test what their own docstrings say they test).

### Blocker C — paper trading had no product surface

**Fix:** new `engine/routers/paper_trading.py` — `GET /api/paper-trades`
(list, `status` filter), `POST /api/paper-trades` (open from an existing
`signal_id`; rejects a missing/nonexistent one with 422/404 and ignores any
other caller-supplied field), `POST /api/paper-trades/{id}/close` (uses
T2's `simulate_exit()` against real OHLCV fetched via
`market_data_provider.get_ohlcv` — returns `{"status":"not_ready"}` rather
than an invented outcome if no price data exists since entry yet), `GET
/api/paper-trades/metrics` (T2's own `compute_metrics()`), `GET
/api/paper-trades/signals` (recent signal_ledger rows, for both picking one
to open and inspecting a trade's originating signal). None of T2's own
logic (`engine/paper_trading/logic.py`) was rewritten — the router only
calls it. `fetch_signal_ledger()` gained one additive `signal_id` filter
(backward-compatible) so the router can validate a real signal rather than
trusting request-body fields.

New `frontend/src/app/paper-trading/page.tsx` (linked from the sidebar):
recent signals with an "Open PAPER TRADE" button, an open-positions table
with "Close PAPER TRADE", a closed-trades table, and portfolio metrics.
Every label says **PAPER TRADE** explicitly; no broker/order-execution
import or call exists anywhere in the new router or page (statically
checked in tests).

**Files:** `engine/routers/paper_trading.py` (new), `engine/utils/db.py`
(`fetch_signal_ledger` signal_id filter), `engine/main.py` (router
registration), `frontend/src/app/paper-trading/page.tsx` (new),
`frontend/src/lib/api.ts` (`paperTradingApi`), `frontend/src/components/Sidebar.tsx`,
`tests/backend/test_paper_trading_router.py` (new).

### Blocker D — production DB could silently fall back to ephemeral SQLite

**Fix:** new `utils.db.validate_database_configuration()`, called once at
`engine/main.py` startup right after H3's CORS validation. Reuses the
identical production-mode convention `_can_use_neon()`/H3's
`is_production_environment()` already use (`FORTRESS_DB_BACKEND` not
`sqlite`/`local`) — no second flag. In production, a missing `DATABASE_URL`
or an unreachable database now raises `RuntimeError` and the app never
starts; dev/local (`sqlite`/`local`) is unaffected. `_can_use_neon()`
itself is untouched — it still returns a plain bool for its many existing
callers; this is a separate, explicit startup gate. Neither error message
includes the connection string or the underlying driver exception text.

**Files:** `engine/utils/db.py`, `engine/main.py`,
`tests/backend/test_database_fail_closed.py` (new).

## E1 integration check (after all of the above)

- **Successful real scan → research_observations for every successfully
  scored ticker:** `test_v4_end_to_end.py::test_full_chain_async_scan_to_paper_position`
  and `test_circuit_breaker_empty_data.py::test_normal_scan_still_produces_e1_observations`.
- **Circuit-broken scan → no misleading observations:**
  `test_circuit_breaker_empty_data.py::test_empty_data_circuit_break_produces_no_e1_observations`
  (row count unchanged after a tripped scan) — this is the fix in Blocker B
  that closes the gap V3's own scan could have contaminated E1 through.
- **Research observation → signal → paper trade link:** the end-to-end
  test opens a paper trade from the exact signal a real scan produced,
  confirming the `(scan_id, symbol)` join E1's docs describe actually
  resolves in practice.
- **Non-signal scored ticker remains a valid observation:** unchanged from
  E1 — `research_observations` is written from the full `score_df`
  regardless of whether a row becomes a signal; this story added no filter
  to that write path.

## Async UX verification

`frontend/tests/scan.test.mjs` (14 tests, all passing): job start rejects a
second submission while one is active, `updateJobStatus` renders the real
stage/progress and never a percentage, `completeJob` stores real results
and clears the job, a failed job surfaces its message and clears the job
id, a refresh with a persisted `jobId` stays `running` (reconnectable) and
resumes polling rather than degrading to `unknown`, and a static check
confirms the screener page actually calls `startScanJob`/`getScanJobStatus`/
`getScanJobResults`. Backend: `test_scan_jobs_api.py` (pre-existing, still
green) plus the new end-to-end test drive job creation → polling →
completion → results retrieval through the real FastAPI app.

## Circuit-breaker verification

Live, reproducing V3's exact finding (`test_circuit_breaker_empty_data.py`):
mocking every ticker's fetch to return an empty `DataFrame` (no exception)
now correctly reports `"failed" >= 10`, `"circuit_breaker_tripped": true`,
and stops well short of scanning the full universe — `check_institutional_fortress`
is confirmed (via a call counter) to never even be invoked on unusable
data. A separate test confirms a real-data rejection (liquidity guard
equivalent) still reports `failed: 0`, `circuit_breaker_tripped: false` —
the fix does not turn legitimate scoring rejections into false failures.

## Paper trading accessibility

Reachable end-to-end through the real API (9 tests in
`test_paper_trading_router.py` plus the compact end-to-end chain test): a
position opens only from a real, existing signal id; a nonexistent id is
rejected (404) and a missing one is rejected (422); fabricated body fields
are ignored in favor of the real signal's own entry/stop/target; closing
uses T2's real `simulate_exit()` against real (mocked-provider) price data
and reports `not_ready` rather than inventing an outcome when no price
data exists yet; a static source check confirms no broker/order-execution
reference exists anywhere in the router.

## Production DB fail-closed verification

Live subprocess boot (not just unit tests), same technique H3 used:

```
$ FORTRESS_DB_BACKEND=neon FORTRESS_JWT_SECRET=<random> FORTRESS_APP_PASSWORD=<secure> \
  FORTRESS_CORS_ORIGINS=https://app.example.com python -c "import main"
RuntimeError: FORTRESS_DB_BACKEND is not sqlite/local (production mode) but
DATABASE_URL is not set. Refusing to start rather than silently falling
back to ephemeral local SQLite storage.

$ FORTRESS_DB_BACKEND=sqlite python -c "import main; print('OK')"
OK
```

8 unit tests cover: dev/local pass, missing `DATABASE_URL` fails, an
unreachable database fails, and (mocked-provider — no real Postgres in
this sandbox, clearly labeled in the test file) a fully secure config with
a reachable connection starts cleanly. Two tests confirm the raised error
never echoes the connection string, host, or password.

## Full regression

```
PYTHONPATH=.:engine .venv/bin/pytest tests/backend -q
464 passed, 4 warnings (pre-existing FastAPI/Starlette deprecation warnings)

cd frontend
npm run test:scan   → 14 passed
npm run test:u2     → 16 passed
npm run lint        → clean
tsc --noEmit        → clean
npm run build       → succeeds, 15 routes prerendered (including /paper-trading)
```

No test requires live external network access. Two pre-existing tests were
corrected because they asserted the exact old bug as expected behavior
(see Blocker B); one pre-existing test-isolation flake
(`test_fresh_bhavcopy_data_is_served_normally`, caused by
`get_ohlcv_provider_preference()`'s 30-second cache surviving across tests
within the same test session) was fixed by having its own reset helper
call the existing `invalidate_ohlcv_provider_preference_cache()`.

## Remaining risks

- **`check_institutional_fortress`'s own internal `except Exception:
  return None`** (a genuine computation error, not empty data) is still
  indistinguishable from a legitimate rejection at the `main.py` level —
  out of scope here (V3 reproduced an empty-*data* outage specifically,
  and this lives inside scoring-adjacent code this story does not touch).
- **No concurrent-job limit at the API level** — `POST /api/scan/jobs`
  will accept a second job for the same user; the UI-level guard (button
  disabled while running) covers the actual product path, per V3's own
  finding that this was low-severity.
- **Paper trading has no per-user scoping** — the `paper_trades` schema
  (T2, unchanged) has no user column; any authenticated user sees the same
  shared trade list. Acceptable for this story's "smallest usable surface"
  scope; would need a schema change to fix, which was explicitly out of
  scope.
- **Still zero real R2/R4 evidence** (per FORTRESS-V1) — this story closes
  integration gaps, it does not and cannot create research evidence. That
  requires real market time, not more code.

## Verdicts

```
SOFTWARE:            GO
PRODUCTION:          GO
EVIDENCE COLLECTION: GO
PAPER TRADING:       GO
LIVE TRADING:        EVIDENCE-LIMITED
```

Software, production configuration, evidence collection, and paper trading
are each independently sound and now actually reachable/enforced end to
end. Live trading remains EVIDENCE-LIMITED, not GO or NO-GO on the merits
of this story: no scoring change was made or evaluated, and per V1, zero
real R2/R4 evidence exists yet to judge whether Fortress's scores predict
anything. That is expected — the next requirement is real market time and
untouched observations accumulating through E1, not more engineering.

## Stop condition

All four V3 integration blockers are closed and this review's verification
is green. Stopping here, as instructed — no further features, no scoring
changes.
