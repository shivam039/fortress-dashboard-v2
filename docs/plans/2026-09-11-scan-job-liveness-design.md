# Scan Job Liveness and Observability Implementation Plan

**Goal:** Keep genuinely active scans fresh while making stale-job diagnosis and frontend recovery explicit.
**Architecture:** Run a cancellable asyncio heartbeat alongside each `_run_scan_job()` execution. Guard heartbeat writes with `status = 'running'`, preserve the existing stale-job recovery, and add non-fatal stage timing/RSS logs. Update the existing scan store and status component without changing scan scoring or provider priority.
**Tech stack:** FastAPI, asyncio, SQLite/Postgres, Python `resource`, Next.js, TypeScript, Node test runner.

---

### Task 1: Add failing backend heartbeat tests

**Files:**
- Modify: `tests/backend/test_scan_jobs_db.py`
- Modify: `tests/backend/test_scan_jobs_api.py`

**Step 1: Write the failing tests**
- Verify a heartbeat refreshes `updated_at` for a running job.
- Verify heartbeat updates affect zero rows for completed/failed jobs.
- Verify a stale job remains recoverable when no heartbeat is sent.
- Verify `_run_scan_job()` heartbeat cancellation does not overwrite completion.

**Step 2: Run tests to verify they fail**
Run: `PYTHONPATH=. .venv/bin/pytest tests/backend/test_scan_jobs_db.py tests/backend/test_scan_jobs_api.py -q`
Expected: failures for the missing heartbeat helper/lifecycle behavior.

### Task 2: Implement guarded heartbeat ownership

**Files:**
- Modify: `engine/utils/db.py`
- Modify: `engine/main.py`

**Step 1: Write minimal implementation**
- Add `heartbeat_scan_job(job_id)` with backend-specific guarded `UPDATE`.
- Add configurable heartbeat interval with a 45-second default.
- Start an asyncio heartbeat task in `_run_scan_job()`.
- Cancel and await it in `finally`; preserve completion/failure writes.

**Step 2: Run focused tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/backend/test_scan_jobs_db.py tests/backend/test_scan_jobs_api.py -q`
Expected: PASS.

### Task 3: Add stage timing and RSS telemetry

**Files:**
- Modify: `engine/main.py`
- Modify: `tests/backend/test_scan_jobs_api.py`

**Step 1: Write failing telemetry tests**
- Verify stage logs include job, stage, duration, and RSS fields.
- Verify RSS measurement failure cannot fail a scan.

**Step 2: Implement telemetry**
- Add a small standard-library RSS helper with Linux/macOS conversion handling.
- Emit one structured log at each required stage boundary and total completion.
- Keep telemetry errors non-fatal and do not alter scan results.

**Step 3: Run focused tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/backend/test_scan_jobs_api.py -q`
Expected: PASS.

### Task 4: Add frontend elapsed and interrupted-job UX

**Files:**
- Modify: `frontend/src/components/ScanStatus.tsx`
- Modify: `frontend/src/lib/scan-state.ts`
- Modify: `frontend/src/app/screener/page.tsx`
- Modify: `frontend/tests/scan.test.mjs`

**Step 1: Write failing frontend tests**
- Verify elapsed output formats seconds, minutes, and long durations.
- Verify stale interruption uses a clear retryable message.
- Verify failed polling stops and clears the active job ID while retaining prior results.
- Verify retry submits a new job.

**Step 2: Implement minimal UI/state changes**
- Replace request-wait wording with human-readable elapsed job time.
- Map the stale backend error to an explicit interrupted state.
- Add a Retry Scan action that starts a new job.
- Preserve previous results with an explicit previous-results label.

**Step 3: Run focused frontend tests**
Run: `cd frontend && npm run test:scan`
Expected: PASS.

### Task 5: Run regression gates and commit

**Files:**
- No additional files.

**Step 1: Run backend regression**
Run: `PYTHONPATH=. .venv/bin/pytest tests/backend -q`

**Step 2: Run frontend regression**
Run: `cd frontend && npm run test:scan && npm run lint && npx tsc --noEmit && npm run build`

**Step 3: Review and commit**
Run:
```bash
git diff --check
git status --short
git add engine/main.py engine/utils/db.py frontend/src/app/screener/page.tsx frontend/src/components/ScanStatus.tsx frontend/src/lib/scan-state.ts tests/backend/test_scan_jobs_db.py tests/backend/test_scan_jobs_api.py frontend/tests/scan.test.mjs docs/plans/2026-09-11-scan-job-liveness-design.md
git commit -m "Add scan job liveness heartbeat and observability"
```
