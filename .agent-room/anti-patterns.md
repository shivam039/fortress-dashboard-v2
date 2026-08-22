# Anti-Patterns Log — app

Negative knowledge: things that have already gone wrong here, so nobody
(human or agent) repeats them. One avoided bug is worth more than one
polished example — keep entries short and concrete.

Append a new entry every time:
- a bug slips through and you find the root cause,
- an approach seemed reasonable but turned out wrong,
- a fix gets reverted because it only patched a symptom.

## Format

```
### YYYY-MM-DD — short title

**What happened:** one or two sentences.
**Root cause:** the actual cause, not the symptom.
**Avoid:** the concrete rule that would have prevented it.
```

<!-- Entries go below this line, newest first. -->

### 2026-08-22 — A test asserting "unset" against a hardcoded key can pass once and fail on rerun

**What happened:** A new `test_bhavcopy_fetch_log_dedup_marker` test asserted `get_bhavcopy_fetch_status("2026-07-01") is None` as its opening line. It passed the first time this test file ran, then failed the next time the full suite ran in the same session.
**Root cause:** This repo's SQLite backend (`FORTRESS_DB_BACKEND=sqlite`) is one real on-disk `fortress_history.db` file, shared across the whole pytest session and persisting between separate `pytest` invocations too — not a fresh `:memory:` database per test run. A hardcoded key/date a test writes to is still sitting in that file the next time the suite runs, so an "is None" / "is unset" assertion against a literal key is only true the very first time.
**Avoid:** Any new test against a real key in this SQLite-backed suite that needs to assert "nothing here yet" should generate a run-unique key (e.g. `f"...{uuid.uuid4().hex[:8]}"`) rather than asserting initial absence for a fixed literal — or restructure the test so it only asserts on the *final* state after writes, which is deterministic regardless of what a previous run left behind.

### 2026-08-22 — "engine."-prefixed imports work locally and fail on Render — silently

**What happened:** Several deferred imports inside `market_data_provider.py` (and one each in `instruments_cache.py`/`indstocks_client.py`) used the absolute form `from engine.utils.indstocks_client import get_client` instead of the bare `from utils.indstocks_client import get_client` used everywhere else in this codebase. This works from the repo root (Python resolves `engine/` as an implicit namespace package) — which is how local dev, this sandbox, and the test suite all run — but Render deploys this service with Root Directory set to `engine`, so on Render `engine` is never importable as a package at all. Every INDstocks OHLCV/LTP call on Render hit `ModuleNotFoundError: No module named 'engine'` inside a caught exception and silently fell back to yfinance, with no test catching it because the tests' own monkeypatches used the same wrong `engine.utils.X` path and so "matched" the bug rather than exposing it.
**Root cause:** Two environments resolve the same import differently, and nothing in the local dev loop or test suite ever runs in the environment (Root Directory=engine) where it breaks. A passing local test suite gave false confidence that this path worked in production.
**Avoid:** Inside `engine/`, always use the bare `utils.X` / `routers.X` / `<package>.X` import form (matching how `main.py` itself is loaded and how every other module in this tree already imports its siblings) — never `engine.X`. When adding a test that mocks an internal module by dotted-string path, double check the target string matches what the *production entrypoint* (`main.py`, in this repo) would actually resolve, not just whatever string happens to make the test pass when run from the repo root alongside other tests.

### 2026-08-22 — A degraded live fetch got written straight into a persistent cache

**What happened:** `routers/reit_invits.py`'s `_get_or_fetch_frame()` called `build_reit_frame()` for a live REIT/InvIT fetch, then unconditionally wrote whatever came back into both the in-process cache and the DB-backed `reit_cache` table — including the case where the fetch's own 45s batch timeout tripped and most/all symbols came back as placeholder rows (`price: None`, `risk_flags: ["fetch_timeout"]`). One slow network patch — a very ordinary occurrence with yfinance on cloud-provider IPs — locked every viewer of the REIT/InvIT tab into seeing blank data for up to `_CACHE_MAX_AGE_HOURS` (4 hours), since the cache doesn't distinguish "this is real, verified-empty data" from "the fetch that was supposed to produce this data never actually completed."
**Root cause:** The persistence step trusted "the fetch function returned without raising" as equivalent to "the fetch succeeded," when the batch-timeout code path deliberately catches its own failure and returns placeholder records instead of raising — exactly so the caller gets *a* response instead of a hang, but that same exception-free return made the failure invisible to the caching layer one level up.
**Avoid:** Whenever a function is designed to degrade gracefully instead of raising on partial/total failure (a very reasonable thing for a batch-timeout path to do), any caller that persists its result must inspect the result's own quality markers (here: `risk_flags`/`price`), not just whether an exception was raised — "didn't throw" and "the data is good" are different claims, and conflating them is exactly how a transient failure becomes a multi-hour outage.

### 2026-08-22 — Guardrails pre-commit hook never actually installed, and its own glob matching was broken

**What happened:** Two compounding gaps. First, `AGENT_ROOM_GUIDE.md` had described `.git/hooks/pre-commit` as an active safety check since this repo's agent-room scaffolding was set up, but `.git/hooks/pre-commit` never actually existed on this machine — `.agent-room/hooks/guardrails-check.js` was fully written but never wired up, so no commit had ever actually been checked. Second, once installed and tested end-to-end with a real staged file (`_hook_test_secret.py` at the repo root), the hook let it through: `isPathProtected()`'s glob-to-regex translation converted `**/*secret*` into a regex that required a literal `/` character, so a protected-path pattern meant to catch files anywhere (including the repo root) only ever matched files nested in a subdirectory.
**Root cause:** (1) `.git/hooks/` is untracked by git by design, so scaffolding a hook's *logic* in a tracked file (`.agent-room/hooks/`) doesn't install it — a separate, machine-local step was always required and got skipped. (2) The naive `pattern.split('*').join('.*')` glob translation cannot express "zero or more path segments, including none," which is exactly what a leading `**/` is supposed to mean.
**Avoid:** When a repo's docs describe a git hook as active, verify `ls -la .git/hooks/<name>` directly rather than trusting the docs — the hook only exists if a file is actually there (git hooks are never synced by cloning/pulling). Separately, any hand-rolled glob matcher must be tested against the specific "no directory prefix" case for `**/`-style patterns, since the common human intuition (and connect-the-dots split/join implementation) both miss it.

### 2026-08-22 — No circuit breaker on /api/scan — individual failures had no aggregate tracking

**What happened:** `run_scan()` caught exceptions per-ticker, logged them, and moved on — but never tracked the failure rate across the whole run. A broad yfinance outage or rate-limit event meant the endpoint would grind sequentially through an entire universe (e.g. Smallcap 250, 250 tickers) with nearly every one failing slowly, and the response looked identical to a legitimate "nothing matched the screen" result — the caller had no way to tell the two apart.
**Root cause:** Per-ticker error handling was built early (before large universes or provider outages were a real concern) and never revisited to add aggregate tracking once the ticker universes and the yfinance dependency both grew.
**Avoid:** Any endpoint that loops over an external, rate-limited/flaky data provider across many items should track a running failure rate and define an explicit abort threshold, not just catch-log-continue per item — and the response shape should let the caller distinguish "provider is down, we gave up early" from "we tried everything and nothing matched."

### 2026-08-22 — Hardcoded auth defaults left unset in production

**What happened:** `FORTRESS_JWT_SECRET` and `FORTRESS_APP_PASSWORD` both had hardcoded fallback values baked into the source (a dev JWT secret string, and the password `fortress123`). Neither was set on the Render production service, and both defaults are now public in git history — meaning production was running with a forgeable JWT secret and a publicly-known admin password.
**Root cause:** Dev-convenience defaults for these two values were never followed up with a loud, unmissable warning (unlike `FORTRESS_API_KEY`, which already had one) or a "required" flag surfaced anywhere a deployer would actually see it before going live.
**Avoid:** Any hardcoded credential/secret default meant only for local dev must (1) log a `WARNING` the moment it's actually used, not just exist as a silent fallback, and (2) be listed as required in the deployment docs' env var table — a default that's "fine for local dev" is never fine to leave undocumented as a production requirement.

### 2026-08-22 — Two Vercel projects silently competing for the same GitHub repo

**What happened:** One Vercel project (`fortress-dashboard-v2`) was connected to the repo but built from the repo root, failing on every single push since the first commit — invisible in the dashboard's deployment list because the Status filter excluded "Error" by default. A second project (`frontend`) was serving the actual working site, but had been deployed manually via the Vercel CLI with no Git connection at all, so it never picked up new commits.
**Root cause:** The repo root contains both `pyproject.toml` (Python tooling config) and `engine/main.py` (a FastAPI `app`), which is enough for Vercel's zero-config framework auto-detection to treat the whole repo as a Python project unless Root Directory is explicitly scoped to `frontend/`.
**Avoid:** In a monorepo with both a Python backend and a JS frontend at different subpaths, always set Vercel's Root Directory explicitly rather than relying on auto-detection from the repo root — and check the Vercel org's full project list (not just one project's deployment history) whenever a build result looks inconsistent with what's actually live.

### 2026-08-22 — Hardcoded tickers guessed from marketing names instead of verified NSE symbols

**What happened:** 5 of 9 entries in the REIT/InvIT universe used ticker symbols guessed from a trust's marketing/brand name (e.g. `BROOKFIELD.NS`, `NHAI.NS`) rather than its actual NSE trading symbol, silently breaking data for those instruments — they'd fail to fetch and just show as blank/loading forever, with no error surfaced.
**Root cause:** No validation step confirming a hardcoded ticker actually resolves on the data provider before shipping it in a universe list.
**Avoid:** When hardcoding a small, high-value ticker universe (REITs, InvITs, indices), verify each symbol resolves via the actual data provider (or add a startup/CI check that fetches each one) rather than trusting a name-based guess.

### 2026-08-22 — Neon connection failure silently degrading production to SQLite

**What happened:** Render's production deployment ran on ephemeral SQLite for a period because `DATABASE_URL` wasn't set — the app logged this at `INFO` level (`"Neon unavailable, falling back to SQLite"`) and kept serving requests normally, so the misconfiguration was easy to miss in a scrolling log and had no user-facing symptom.
**Root cause:** The Neon-unavailable fallback path is designed for local-dev convenience (never require credentials to start locally), but the same code path applies unchanged in production too, where an ephemeral SQLite file loses all data on every redeploy/restart.
**Avoid:** In production specifically, a Neon-unavailable fallback should log loud enough to be noticed (`ERROR`/alert-worthy), not `INFO` — worth a follow-up to make `_can_use_neon()`'s failure log level environment-aware (e.g. `ERROR` whenever `FORTRESS_DB_BACKEND` isn't explicitly `sqlite`/`local`) so this can't happen unnoticed again.

### 2026-07-10 — Flattening scores to 50.0 in zero-variance universes or single stock scans

**What happened:** Single stock scans or lists of stocks with identical raw values got their final conviction scores flattened to a constant `50.0`.
**Root cause:** Universe-relative normalization divided by zero and defaulted to `50.0` for all categories.
**Avoid:** When the range of values is zero (`max_v == min_v`), fall back to returning the absolute values (clamped to `[0, 100]`) rather than a constant average indicator.

### 2026-07-10 — Test Suite database hangs and safe_session_state dictionary access

**What happened:** Running frontend tests caused the test suite to hang indefinitely or throw AttributeErrors.
**Root cause:**
1. The Streamlit app initialized Neon connection checking on startup, which blocked on connection attempts.
2. The `AppTest` wrapper's safe session state does not support the dict `.get()` method.
**Avoid:**
1. Force `FORTRESS_DB_BACKEND=sqlite` in the test environment configuration to bypass remote DB connection attempts.
2. Do not use `.get()` on Streamlit's `AppTest.session_state` object; use square bracket index access or `getattr()`.
