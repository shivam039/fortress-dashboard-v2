# Decisions Log — app

Short, append-only record of architecture/design decisions and why. A
decision belongs here if a future session (or a future you) would otherwise
have to re-derive it from scratch by reading git history.

## Format

```
### YYYY-MM-DD — short title

**Decision:** what was decided.
**Why:** the constraint or trade-off that drove it.
**Rejected:** what else was considered, and why it lost.
```

<!-- Entries go below this line, newest first. -->

### 2026-08-22 — Make NSE Bhav Copy the default OHLCV/scan data source, with a UI toggle back to IndMoney/INDstocks

**Decision:** Added a new `engine/bhavcopy/` module (`logic.py` fetch+parse, `jobs.py` refresh job + one-off backfill) that downloads NSE's daily UDiFF common Bhav Copy (`https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`), parses it, and accumulates it into a new `bhavcopy_eod` table (`PRIMARY KEY (symbol, trade_date)`, dual SQLite/Neon, in `utils/db.py`). A separate `bhavcopy_fetch_log` table is the actual "don't re-fetch today's file" guard the daily job checks before any network call — `bhavcopy_eod`'s own upsert idempotency only makes repeat *writes* safe, it doesn't skip the *fetch*. `market_data_provider.get_ohlcv()`/`get_batch_ohlcv()` gained a Bhav Copy tier that's tried first when a new `app_settings` key `ohlcv_provider_preference` (default `"bhavcopy"`) says so, falling through to INDstocks then yfinance exactly as before when Bhav Copy has no data for a symbol/range — read through a 30s in-process TTL cache so the setting doesn't cost a DB round trip on every OHLCV call, invalidated immediately on write. `get_ltp()`/`get_batch_ltp()` are deliberately untouched: Bhav Copy is EOD-only, so live price always stays INDstocks -> yfinance regardless of the toggle — `provider_status()` now reports `ohlcv_source`/`ohlcv_source_label` (the OHLCV/scan preference) separately from the pre-existing `primary`/`primary_label` (the live-price source), and the frontend `SystemStatus.tsx` badge shows both, with a click-to-toggle control hitting the new `GET`/`POST /api/settings/data-provider` endpoints (`engine/routers/bhavcopy.py`). A weekday GitHub Actions workflow (`.github/workflows/bhavcopy-refresh.yml`, following the `keepalive.yml` precedent of a scheduled HTTP call against the deployed backend rather than any OS-level cron, which this repo doesn't have) POSTs `/api/bhavcopy/refresh` at 19:00 and 20:30 IST — the second run exists because NSE's publish window is inconsistent and the job already treats a 404 as `"not_yet_published"` rather than an error, so a harmless retry is exactly what should happen.
**Why:** The user asked to discuss and then plan-then-implement a Bhav Copy integration, driven by repeated INDstocks/IndMoney production failures this session (TOTP secret validation, "No module named 'engine'" on Render, REIT/InvIT batch timeouts) and the fact that Bhav Copy has no per-symbol rate limit or auth to break. Verified beforehand (in the discussion phase) that Bhav Copy's OHLC/volume/turnover coverage maps to exactly the `technical_raw` (50%) + `context_raw` (10%) + liquidity-gate portion of the conviction score — 60% of the weighted score — while `fundamental_raw` (analyst targets) and `sentiment_raw` (news/earnings) genuinely require yfinance and are untouched by this change. The user explicitly asked for IndMoney to stay available via toggle ("since we invested so much in indmoney") rather than being ripped out, and for Bhav Copy to be the default.
**Rejected:** Reusing the existing `ohlcv_cache` table (whole-DataFrame-per-symbol-per-period JSON blob) for Bhav Copy storage. Rejected because Bhav Copy is inherently row-per-symbol-per-day and needs to answer arbitrary "last N days" queries as history accumulates day by day — a blob cache can only answer the exact period it was written for. Also rejected: an in-job network retry/poll loop for a not-yet-published file, in favor of two independently scheduled GitHub Actions cron entries — simpler, and consistent with the dedup-log design already treating "not yet published" as a normal, retryable state rather than a failure.

### 2026-08-22 — Test-file lesson while building the Bhav Copy dedup-log tests: don't hardcode a literal date/key in a test against the file-backed SQLite dev DB

**Decision:** `tests/backend/test_bhavcopy.py`'s `bhavcopy_fetch_log` dedup test originally asserted `get_bhavcopy_fetch_status("2026-07-01") is None` as its first line. It passed in isolation but failed when the full suite ran a second time in the same session, because this repo's SQLite backend is one on-disk `fortress_history.db` file shared across the whole pytest session (not a fresh `:memory:` db per run) — a prior run's `record_bhavcopy_fetch("2026-07-01", ...)` call left a real row behind, so a later run's "is None" assumption about a hardcoded key was never actually guaranteed. Fixed by generating a run-unique key (`f"...{uuid.uuid4().hex[:8]}"`) instead of asserting initial absence for a fixed literal.
**Why:** Found by literally re-running the full suite twice during this same implementation and watching a previously-green test fail the second time — the fix is recorded here (rather than left as a silent one-line diff) because it's a general trap for any *new* test in this repo that checks "is not yet set" against a real key, not specific to Bhav Copy.
**Rejected:** Wiping/recreating `fortress_history.db` between test runs. Rejected as out of scope for this change — it would affect every other test file's assumptions about persisted fixtures, not just this one.

### 2026-08-22 — Sharpen the INDSTOCKS_TOTP_SECRET validation error instead of chasing a code bug that wasn't there

**Decision:** After the previous entry's import fix reached Render (confirmed: the "No module named 'engine'" error is gone from the logs), the next log batch showed `_generate_totp_code()` correctly rejecting the configured `INDSTOCKS_TOTP_SECRET` as not valid base32 — this is a real problem with the *value* set on Render, not a code bug (the existing whitespace-stripping/uppercasing logic, added earlier this session, is already correct and was already tested). Rather than guess at the user's actual secret (never appropriate — this session's standing rule is to never touch a live credential shared in chat, and the user correctly didn't paste it), improved the error itself to be self-diagnosing: (1) it now names which specific character(s) in the configured value aren't valid base32 (e.g. `['0', '9']`) without echoing the secret itself, since 0/1/8/9 are never valid base32 digits and are also the most common visual-transcription mistakes (0↔O, 1↔I/l, 8↔B, 9 has no lookalike but shows up from fat-fingering); (2) it now handles the case where a dashboard's copy button grabs the full `otpauth://totp/...?secret=...` QR-provisioning URI instead of the bare secret — a very common TOTP setup mistake — by parsing it with `pyotp.parse_uri()` instead of failing the base32 check on the surrounding URI text.
**Why:** The user asked to diagnose a Render log; the honest diagnosis was "your INDSTOCKS_TOTP_SECRET value is wrong, not the code" — but leaving it at that would mean the user has to re-guess what's wrong with a value neither of us can see together. A sharper error message is the correct fix on the code side of this boundary.
**Rejected:** Asking the user to paste the actual secret value into chat to debug it directly. Rejected on the same standing security principle applied all session to the Neon API key — a shared secret in a chat transcript should be treated as compromised, and diagnosing it that way would mean recommending its rotation immediately after, which is worse for the user than a slightly slower self-service fix.

### 2026-08-22 — Fix INDstocks "No module named 'engine'" on Render; cool down repeated REIT/InvIT live-fetch attempts

**Decision:** Two more fixes from a fresh batch of pasted Render logs (the same deploy that still showed the REIT/InvIT timeout — predates the previous entry's fix, which hadn't been pushed yet):
1. `market_data_provider.py`, `instruments_cache.py`, and `indstocks_client.py` had several *executable* (not just docstring) imports of the form `from engine.utils.indstocks_client import get_client` — absolute, "engine."-prefixed paths. These work by accident when running from the repo root (Python's implicit namespace-package resolution finds `engine/` as a package), which is how local dev and this sandbox always run — but Render deploys this service with **Root Directory set to `engine`**, so `engine/` itself is the process's working directory and `engine` is never importable as a package there at all. Every INDstocks OHLCV/LTP call on Render has therefore been hitting `ModuleNotFoundError: No module named 'engine'` inside a caught exception, silently falling back to yfinance — meaning the TOTP auto-refresh INDstocks integration (see the "IndStocks TOTP auto-refresh" decision entry) has likely never actually been used in production, on top of the separate `_indstocks_available()` availability-detection bug fixed earlier this session. Changed all of them to the bare `utils.X` form already used everywhere else in this codebase (main.py, the routers, stock_scanner), which resolves correctly in both environments. Also fixed `tests/backend/test_market_data_provider.py`'s monkeypatch targets, which patched the same now-wrong `engine.utils.X` paths (they "worked" only because they matched the code's own bug) — and added the `engine/` sys.path setup to `tests/conftest.py` itself, since without it these tests only passed when some *other* test file that imports `engine.main` happened to run first in the same pytest session, an order-dependence a plain `pytest tests/backend/test_market_data_provider.py` in isolation exposed immediately once the code no longer matched the tests' bad patch target.
2. Render logged a "Web Service exceeded its memory limit" auto-restart alongside the REIT/InvIT timeout warning. The previous entry's `_call_with_timeout` + "don't cache a degraded frame" fixes, combined, meant every single incoming `/api/reit-invits` request during a sustained provider outage would trigger its own full live-fetch attempt — each spinning up roughly two dozen threads (an outer pool of 6, plus up to two single-use `_call_with_timeout` executors per symbol), abandoned rather than killed if still blocked when their timeout fires. Under real request volume during an extended outage that's unbounded thread growth — very plausibly a real contributor to the memory restart. Added a short (3-minute) in-process cache TTL specifically for degraded frames (distinct from the healthy-frame 4-hour TTL, tracked via a new `_cache_is_degraded` flag) so repeat requests during that window are served from cache instead of each re-triggering `build_reit_frame()`.
**Why:** Pasted Render logs showed the exact `ModuleNotFoundError` and the memory-limit restart notice back to back. Root-caused (1) by testing the same import from the repo root (works) vs. simulating Render's actual documented deployment layout; root-caused (2) by re-reading the previous entry's own fix with fresh eyes and recognizing "retry on every request, forever, during an outage" as the predictable consequence of "stop caching bad data" without a companion rate limit.
**Rejected:** For (2), reducing `_BATCH_TIMEOUT_S` or the thread-pool sizes instead of adding a retry cooldown. Rejected because that only shrinks each individual attempt's cost, not how often attempts happen — the cooldown addresses the actual unbounded-growth mechanism directly. Instance sizing (Render plan upgrade) is a legitimate independent lever if memory pressure persists after this, but is a cost/capacity decision for the user, not a code fix.

### 2026-08-22 — Fix Scan History persistence (was never wired up) and REIT/InvIT live-fetch timeout/cache-poisoning

**Decision:** Two unrelated but adjacent fixes, both requested together as "broken scan history" and a pasted REIT/InvIT timeout log line:
1. **Scan History was always empty.** `/api/scan` in `main.py` — what the real Next.js frontend calls — never called `register_scan`/`save_scan_results` at all; only the legacy Streamlit UI's `_save_scan()` and the standalone Telegram bot script did. Wired up the same pattern (`register_scan(..., scan_type="STOCK", status="Completed")` then `save_scan_results(scan_id, scored_df, scan_timestamp=...)`) in both of `run_scan()`'s return paths (normal and circuit-breaker-tripped-with-partial-results), best-effort (a history-write failure logs a warning but never fails the scan response). While building an end-to-end test for this, found a second, independent bug in the read path: `fetch_history_data()` in `db.py` pulled `scan_id` out of a pandas DataFrame via `.iloc[0]["scan_id"]`, which returns a `numpy.int64` — passed as a bind parameter to `pd.read_sql_query` on a raw sqlite3 connection, sqlite3 doesn't recognize that type and the query silently matches zero rows (no exception). So even a scan that *did* get recorded in the `scans` table would show a valid timestamp in the dropdown but zero rows of data. Fixed by casting to a plain `int()`.
2. **REIT/InvIT "N/N symbols still pending" timeout.** `_compute_raw_metrics()` makes 3 sequential yfinance calls per symbol (`yf.download` for price history, `Ticker.dividends`, `Ticker.info`), only the first of which takes an explicit timeout — `Ticker.info`/`.dividends` have been observed taking most of a minute on a slow/rate-limited connection (yfinance from cloud-provider IPs, Render included, is frequently throttled), so 2-3 such calls per symbol can blow past the whole batch's 45s budget before even the first of 6 concurrently-running symbols finishes. Added `_call_with_timeout()`, a small helper that runs a callable on a throwaway thread and gives up after 12s, and used it for the two previously-unbounded calls. Separately — the more consequential half of this — found that a timed-out/degraded live fetch was being written straight into the DB-backed `reit_cache` table (`upsert_reit_cache`) and the in-process cache, meaning one slow patch poisoned the REIT/InvIT tab with blank placeholder data for up to `_CACHE_MAX_AGE_HOURS` (4 hours) for every viewer, instead of the next request just retrying. Added `_is_degraded_frame()` in `routers/reit_invits.py`: a freshly-fetched frame where >30% of rows are placeholder/error is served for that one request but not persisted anywhere, so the next request gets a real retry instead of being stuck.
**Why:** User reported scan history as broken and pasted a Render log line showing all 11/11 REIT/InvIT symbols timing out. Both root causes were verified directly (an end-to-end test reproducing the exact "timestamp exists, zero data rows" symptom before the `int()` fix; a direct reproduction of the cache-poisoning path before the degraded-frame gate).
**Rejected:** Increasing `_BATCH_TIMEOUT_S` (the batch-level 45s cap) instead of bounding the individual calls. Rejected because a longer batch timeout doesn't fix the underlying problem (a single hung call still eats the whole budget) and just makes every request slower to fail when the provider really is down — bounding each call is what actually gives more symbols a chance to finish within the same window.

### 2026-08-22 — Wire up the pre-commit guardrails hook; fail-fast on default JWT secret in prod-like environments; CI build check; placeholder client ID in docs

**Decision:** Four related fixes from a second pasted review (which turned out to be reviewing public `main`, one commit behind this repo's local history):
1. Installed `.git/hooks/pre-commit` on the user's machine to actually call the pre-existing (but never wired up) `.agent-room/hooks/guardrails-check.js`. While testing it end-to-end, found and fixed a real bug in `isPathProtected()`: its glob translation required a literal `/` for any `**/`-prefixed pattern (e.g. `**/*secret*`), so it silently never matched protected files sitting at the repo root — only ones nested in a subdirectory. Rewrote the glob-to-regex translation to treat `**/` as an optional path prefix.
2. `engine/auth_utils.py` now hard-fails at import time (`RuntimeError`) if `FORTRESS_JWT_SECRET` is unset/default AND `FORTRESS_DB_BACKEND` is not explicitly `sqlite`/`local` — i.e. anything that isn't opted into local dev is treated as production-like and refuses to start with a forgeable, publicly-known JWT secret. Local dev and the test suite are unaffected (both already set `FORTRESS_DB_BACKEND=sqlite`).
3. Added `.github/workflows/ci.yml`: backend `pytest tests/backend` and frontend `npm run lint` + `npm run build` on every push/PR to `main`. The repo previously only had `agent-room-validate.yml` (structure/session-log linting) — no actual test/build gate existed.
4. Replaced the real-looking `INDSTOCKS_CLIENT_ID=dX03OgVqr0Cgc8x7fJQ0` example in `README.md`/`DEPLOYMENT.md` (4 occurrences) with `<your_client_id>`, matching the placeholder style already used for `INDSTOCKS_MPIN`/`INDSTOCKS_TOTP_SECRET` on the same lines.
**Why:** The review flagged (2)-(4) as still-open gaps, and separately the user asked to finally wire up the pre-commit hook the docs had described as active since well before this session (a previously-logged anti-pattern/gap). (2) upgrades the prior warn-only stance (see the previous "Warn loudly..." entry) now that the review raised it a second time — a warning in a scrolling Render log is easy to miss, a refusal to boot is not.
**Rejected:** Fail-fast unconditionally (regardless of `FORTRESS_DB_BACKEND`). Rejected because it would break the documented local-dev flow for anyone who forgets to export `FORTRESS_DB_BACKEND=sqlite` — conditioning on the existing local/dev signal keeps local dev frictionless while closing the real production gap.

### 2026-08-22 — Circuit breaker for /api/scan instead of an unbounded per-ticker retry loop

**Decision:** Added a failure-rate circuit breaker to `run_scan()` in `main.py`: once at least 10 tickers have been attempted, if the failure rate is ≥80%, stop scanning the rest of the universe and return whatever partial results exist, with `scanned`/`failed`/`circuit_breaker_tripped` fields and a summary that distinguishes "aborted early — provider likely down" from "nothing matched the screen." Did not add concurrency (parallel ticker fetches) in the same change.
**Why:** A pasted review flagged that individual ticker errors were logged and skipped with no aggregate tracking, so a broad yfinance outage or rate-limit meant grinding sequentially through an entire universe (e.g. Smallcap 250) with each ticker failing slowly, and the caller had no way to tell a real outage apart from a screen that legitimately matched nothing.
**Rejected:** Parallelizing the ticker loop (ThreadPoolExecutor) to also fix scan *speed* for large universes. Rejected for this change specifically — hitting yfinance/INDstocks concurrently needs careful worker-count tuning to avoid making rate-limiting worse, which is a bigger, riskier change than a bounded early-abort; flagged as a separate follow-up rather than bundled in.

### 2026-08-22 — Warn loudly instead of silently trusting hardcoded auth defaults

**Decision:** Added startup-time `WARNING` logs in `auth_utils.py` (JWT secret) and `routers/auth.py` (admin password) whenever `FORTRESS_JWT_SECRET` / `FORTRESS_APP_PASSWORD` fall back to their hardcoded dev defaults, matching the existing pattern already used for `FORTRESS_API_KEY`. Also documented all three as required Render env vars in `DEPLOYMENT.md`, with the JWT secret added to the env var reference table for the first time (it wasn't listed there at all).
**Why:** A pasted security review flagged that both defaults are hardcoded strings now public in this repo's git history — anyone can forge an admin JWT or log in as admin outright on any deployment that doesn't override them. Warning (not hard-failing) keeps local dev frictionless while making the production risk impossible to miss in Render's logs.
**Rejected:** Refusing to start the app when these are unset outside local dev. Rejected for now to stay consistent with the existing `FORTRESS_API_KEY` precedent (warn, don't block) rather than introducing an inconsistent enforcement model — worth revisiting if this keeps getting missed in practice.

### 2026-08-22 — Retire the stray [tool.vercel] entrypoint; scope Vercel to frontend/ only

**Decision:** Removed `[tool.vercel]` from `pyproject.toml` (which had declared `engine.main:app` as a Vercel entrypoint) and instead configured the Vercel project's Root Directory to `frontend/`, deploying only the Next.js app to Vercel.
**Why:** The FastAPI backend already deploys to Render with its own env vars (Neon `DATABASE_URL`, INDstocks TOTP secrets, `FORTRESS_API_KEY`). Building it a second time on Vercel from the repo root also caused Vercel's Python auto-detection to fail outright ("No FastAPI entrypoint found"), and would have meant maintaining two divergent backend deployments with separate, easily-drifting config.
**Rejected:** Fixing the Vercel entrypoint declaration to make the dual-deployment work. Rejected because a second live backend copy — likely missing production env vars — adds real operational risk for no benefit; Render already serves this role.

### 2026-08-22 — REIT/InvIT distribution-history scoring and cache-backed, non-blocking route handlers

**Decision:** Fixed 5 incorrect REIT/InvIT NSE tickers (previously guessed from marketing names rather than verified against actual trading symbols), added 1y/3y distribution-history scoring pulled from `yfinance` dividends, and converted `list_reit_invits`/`get_reit_detail`/`reit_refresh_status` from `async def` to `def` with an in-memory → DB-cache → live-fetch resolution order.
**Why:** The REIT/InvIT tab was reported as permanently stuck loading. Root cause was a combination of wrong tickers silently failing to fetch data, `async def` route handlers wrapping slow synchronous yfinance calls (blocking uvicorn's entire event loop for every request on the server, not just REIT/InvIT ones), and a completely unimplemented cache layer (`upsert_reit_cache` was a no-op placeholder).
**Rejected:** Keeping the async signature and just optimizing the yfinance calls. Rejected because the blocking-event-loop bug affects the whole server, not just this endpoint's own response time — the signature itself was the defect, matching a fix pattern already established elsewhere in this app (scanner, sector-pulse, MF routes).

### 2026-08-22 — IndStocks TOTP auto-refresh for a credential-free unattended deployment

**Decision:** Verified via full code audit (`indstocks_client.py`, `market_data_provider.py`, `main.py`) that the app runs safely with zero INDstocks credentials locally (transparent yfinance fallback via `_indstocks_available()` gating before any client is constructed), and documented that Render production should use the TOTP trio (`INDSTOCKS_CLIENT_ID`/`MPIN`/`TOTP_SECRET`) rather than the static `INDSTOCKS_TOKEN`, since the static token expires every 24h with no one present on an unattended server to manually refresh it.
**Why:** User needed to deploy the backend to Render (no human present to refresh a 24h token) while also being able to run locally without ever entering credentials.
**Rejected:** A cron job or separate refresh service to rotate `INDSTOCKS_TOKEN` on a schedule. Rejected because the TOTP trio already lets the app self-refresh on any `403`, entirely inside the running process — no separate process, cron, or webhook required.

### 2026-08-21 — Configure Vercel FastAPI entrypoint

**Decision:** Declare `engine.main:app` in the `[tool.vercel]` section of
`pyproject.toml` so Vercel can deploy the repository-root FastAPI backend.
**Why:** Vercel's build could find the application but could not select an
entrypoint automatically.
**Rejected:** Moving or duplicating the FastAPI app into a default location.
Rejected because the existing module is already the canonical backend entrypoint.

### 2026-07-10 — Final cleanup standardizes formatting and repository layout

**Decision:** Added explicit formatter/linter configuration in `pyproject.toml`, ran `isort`, `black`, and `ruff` across the Python project, kept legacy modules excluded from Ruff enforcement, and moved the cron setup utility into `scripts/`.
**Why:** The development-db branch needed a consistent, review-ready baseline without changing core business behavior. Formatting the full Python tree makes future diffs smaller and easier to review, while excluding legacy modules avoids turning archival code into an unrelated cleanup project.
**Rejected:** Selectively formatting only touched files. Rejected because the requested final cleanup pass specifically asked to run project formatting tools and improve overall structure.


### 2026-07-10 — Adopt multi-layer ui/ architecture (internal single-page routing)

**Decision:** Extracted the 1,626-line `streamlit_app.py` monolith into a structured `ui/` package:
- `ui/state.py` — central state manager with typed getters, `bootstrap()`, `require_login()`, and broker cache helpers
- `ui/components/` — reusable widgets: `auth`, `broker`, `orders`, `profile`, `sidebar`
- `ui/utils/` — pure helpers: `formatting`, `scan` (run_scan_directly / fetch_universes), `telegram`
- `ui/views/` — one `render()` entry-point per module: dashboard, stock_screener, mf_lab, orders, commodities, options, history
- `streamlit_app.py` reduced to ~200 lines (path setup + bootstrap + sidebar + routing only)
**Why:** Adopted internal single-page routing (not `pages/` folder) because `pages/` does not automatically apply the auth gate — each sub-page file would need its own `require_login()` check, increasing boilerplate and risk of auth bypass. Internal routing keeps a single `st.stop()` as the auth gate.
**Rejected:** Streamlit `pages/` folder. Rejected because the auth gate must protect every module and `pages/` has no built-in auth guard.



### 2026-07-10 — Improve normalization fallback for zero-variance universes and single stock scans

**Decision:** Modified `_normalize_series` in `engine/stock_scanner/logic.py` to return the absolute values (clamped to `[0, 100]`) instead of forcing them to a constant `50.0` when `max_v == min_v`.
**Why:** To ensure that single stock scans or uniform lists (zero variance) reflect the correct raw technical/fundamental scores rather than degrading/inflating all values to a middle-of-the-road average.
**Rejected:** Forcing a constant `50.0` or raising an exception.

### 2026-07-10 — Resolve test suite execution hangs and logic errors

**Decision:** Optimized repository test suite execution and fixed logic bugs in mutual fund tools:
1. Configured local test environment `conftest.py` to force `FORTRESS_DB_BACKEND=sqlite` to prevent execution hangs from attempting connections to PostgreSQL/Neon.
2. Updated `detect_integrity_issues` in `mf_lab/logic.py` to align indices on `'date'` when it is present as a column, resolving testing alignment errors.
3. Corrected safe_session_state lookup syntax in `tests/frontend/test_login.py`.
4. Completed implementation of `render_selected_schemes_analysis` in `ui_scheme_discovery.py` replacing the TODO placeholder with the real `fetch_mf_snapshot` call.
**Why:** To ensure 100% passing tests, zero execution hangs, and complete, functional mutual fund scheme browsing/analysis.
**Rejected:** Leaving tests disabled or stubs. Rejected because maintaining a clean, passing test suite is key to code quality and prevents regressions.

### 2026-07-10 — Prevent commits from corporate email addresses

**Decision:** Modified the pre-commit guardrails hook to strictly prevent commits using corporate email addresses (`shivam.dixit@publicissapient.com` and `shidixit2@publicisgroupe.net`).
**Why:** To enforce repository security constraints requiring all contributions to use `shivamdixit039@gmail.com` as the commit author/committer.
**Rejected:** Checking the email inside `.git/hooks/pre-commit` itself. Rejected because `.git/` is not committed/shared, whereas `.agent-room/hooks/guardrails-check.js` is tracked in git and will be distributed to all clones/agents.

### 2026-07-10 — Scaffold full agent-room profile

**Decision:** Scaffolded the full agent-room profile, including coordination protocols, principles.md, workflow-classifier.md, and configured .agent-room.json to use "profile": "full".
**Why:** To ensure the workspace has all the recommended agent-room files and matches the specifications referenced in AGENTS.md.
**Rejected:** Keeping the minimal profile. Rejected because AGENTS.md specifically directs agents to read .agent-room/principles.md and workflow-classifier.md, which were missing in the minimal profile.
