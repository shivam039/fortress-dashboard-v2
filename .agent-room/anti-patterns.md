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
