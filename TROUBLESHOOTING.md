# Troubleshooting Guide — Fortress Dashboard

> Collect error symptoms here. If you solve a new issue, add it to this file.

---

## Table of Contents

1. [Startup / Import Errors](#1-startup--import-errors)
2. [Database / Connection Issues](#2-database--connection-issues)
3. [Stock Scanner Problems](#3-stock-scanner-problems)
4. [Mutual Fund Lab Issues](#4-mutual-fund-lab-issues)
5. [Authentication & Login Issues](#5-authentication--login-issues)
6. [Telegram Alerts Not Working](#6-telegram-alerts-not-working)
7. [Test Failures](#7-test-failures)
8. [Performance Issues](#8-performance-issues)
9. [Deployment Issues](#9-deployment-issues)

---

## 1. Startup / Import Errors

### `ModuleNotFoundError: No module named 'utils'` on startup

**Cause:** The `engine/` directory is not in `sys.path`.

**Fix:** Always run from the repo root:
```bash
cd fortress-dashboard
streamlit run streamlit_app.py
```

`streamlit_app.py` inserts both `ROOT_DIR` and `ENGINE_DIR` into `sys.path` at startup.

---

### `ImportError: cannot import name 'pandas_ta'` or similar

**Cause:** `pandas-ta-classic` replaces the original `pandas-ta`. Some older code imports `pandas_ta` directly.

**Fix:** The repo uses the compatibility shim at `engine/pandas_ta.py`. If you see this error:
```bash
pip install pandas-ta-classic
```

---

### App hangs on startup with a blank spinner

**Cause:** `init_db()` is trying to connect to Neon Postgres but `DATABASE_URL` is not set or unreachable.

**Fix:** Use SQLite for local development:
```bash
export FORTRESS_DB_BACKEND=sqlite
streamlit run streamlit_app.py
```

---

### `TypeError: argument of type 'NoneType' is not iterable`

**Cause:** Session state accessed before `State.bootstrap()` is called.

**Fix:** Ensure `State.bootstrap()` is the first call after `st.set_page_config()` in `streamlit_app.py`. This is already handled in the current entry point — do not move it.

---

## 2. Database / Connection Issues

### `psycopg2.OperationalError: could not connect to server`

**Cause:** Neon Postgres connection string is wrong or the Neon project is paused (free tier pauses after inactivity).

**Fix:**
1. Go to [console.neon.tech](https://console.neon.tech) and check project status.
2. Click **Resume** if paused.
3. Verify `DATABASE_URL` is the **pooled** connection string (not the direct one).

---

### `sqlalchemy.exc.ProgrammingError: relation "users" does not exist`

**Cause:** Tables were not created yet on a fresh Neon database.

**Fix:** `init_db()` is idempotent and creates all tables. Force it to run:
```bash
PYTHONPATH=.:engine python3 -c "from utils.db import init_db; init_db()"
```

Or run `python3 scripts/fix_missing_tables.py` from the repo root.

---

### Reads/writes working but extremely slow

**Cause:** Using the **direct** Neon connection string instead of the **pooled** one.

**Fix:** In the Neon dashboard → Connection Details → select **Pooled** mode. The pooled URL contains `-pooler` in the hostname.

---

### `FORTRESS_DB_BACKEND=sqlite` but tables are missing after restart

**Cause:** The SQLite file was deleted or you're pointing to a different working directory.

**Fix:** The SQLite file is created at `fortress_history.db` relative to where you run the app. Always run from the repo root. Check:
```bash
ls -lh fortress_history.db
```

---

## 3. Stock Scanner Problems

### Scan returns 0 results

**Possible causes and fixes:**

| Cause | Fix |
|---|---|
| All stocks filtered by Quality Gate | Lower the Market Cap / Liquidity / Price gates in ⚙️ Advanced Settings |
| Universe has fewer than 210 days of history | Use a larger index (Nifty 50) for testing |
| Yahoo Finance rate-limited | Wait 30–60 seconds and retry |
| `FORTRESS_DB_BACKEND=neon` but Neon is paused | Switch to SQLite or resume Neon |

---

### `KeyError: 'Above_EMA200'` in screener results

**Cause:** The stock does not have enough history to calculate a 200-day EMA (requires ≥ 210 trading days of data).

**Fix:** The scanner already filters stocks with `len(hist) < 210`. If you're seeing this error in post-processing, the DataFrame may have been constructed from cached results with missing columns. Clear the screener cache:
```python
# In the Streamlit sidebar → Settings → clear session state
del st.session_state["screener_results"]
```

---

### `ZeroDivisionError` in normalization

**Cause:** All stocks in the universe scored the same raw value (zero-variance universe). Fixed in `_normalize_series` — update if you see this on an older branch.

**Diagnosis:**
```bash
PYTHONPATH=.:engine python3 -c "
from engine.stock_scanner.logic import _normalize_series
import pandas as pd
s = pd.Series([50.0, 50.0, 50.0])
print(_normalize_series(s))  # Should return absolute values, not raise
"
```

---

## 4. Mutual Fund Lab Issues

### MF Lab shows "No data available" after triggering a job

**Cause:** The background job has not finished yet, or it failed silently.

**Fix:**
1. Check the Job Status badge at the top of MF Lab — it shows running/completed/failed.
2. Check `logs/ai_audit_log.jsonl` for job completion entries.
3. Wait ~30 seconds and refresh the page.

---

### `mftool` fails to fetch NAV data

**Cause:** MFAPI.in is occasionally unreliable.

**Fix:** Retry after a few minutes. The NAV cache prevents repeated fetches:
- Cache age: 20 hours by default
- To force a refresh: trigger a **Full Refresh** job with **Force Refresh** checked

---

### MF job hangs (in-process mode)

**Cause:** `_run_job_sync()` is blocking the thread for a large universe. Long-running jobs (> 5 minutes) will eventually complete — the UI shows the elapsed time via the auto-refresh badge.

**Fix for permanent solution:** Deploy the FastAPI backend so MF jobs run server-side. See [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 5. Authentication & Login Issues

### "Invalid credentials" even with correct password

**Cause:** `FORTRESS_APP_PASSWORD` is set but doesn't match what you're typing.

**Fix:**
```bash
echo $FORTRESS_APP_PASSWORD   # check what's set
```

For Streamlit Cloud, verify the secret is set correctly in the app's **Secrets** tab.

---

### Login screen loops after signing in

**Cause:** `st.rerun()` was called but session state was not properly set.

**Diagnosis:** Open browser DevTools → Application → Session Storage. Check if `logged_in` is `True`.

**Fix:** Clear browser cookies/storage and try again. If persistent, check `State.bootstrap()` is called before any rendering in `streamlit_app.py`.

---

### Signup creates account but login fails immediately

**Cause:** Password hashing mismatch — `upsert_app_user()` may have been called without `password=` parameter, leaving `password_hash` as NULL.

**Fix:** Re-register with a new username, or directly update the hash in the DB:
```sql
UPDATE app_users SET password_hash = crypt('yourpassword', gen_salt('bf')) WHERE username = 'youruser';
```

---

## 6. Telegram Alerts Not Working

### Tips send successfully but no message received

**Cause:** Wrong `TELEGRAM_CHAT_ID`.

**Fix:**
1. Have the user send a message to your bot.
2. Fetch updates: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find the `chat.id` field in the JSON response.
4. Update the subscriber list in the Streamlit UI → **📢 Telegram Alert Settings**.

---

### `401 Unauthorized` from Telegram API

**Cause:** `TELEGRAM_BOT_TOKEN` is wrong or the bot was revoked.

**Fix:** Generate a new token via [@BotFather](https://t.me/botfather) → `/token`.

---

### Broadcast works from sidebar but not from the scheduler

**Cause:** The scheduler reads `engine/scripts/telegram_subscribers.txt` — this file may be empty or not saved.

**Fix:** In the UI → **📢 Telegram Alert Settings** → click **💾 Save Subscriber List**. This writes the file.

---

## 7. Test Failures

### Tests hang indefinitely

**Cause:** `AppTest` is trying to connect to Neon on startup.

**Fix:** `tests/conftest.py` must set `FORTRESS_DB_BACKEND=sqlite` before any imports. Check:

```python
# tests/conftest.py
import os
os.environ["FORTRESS_DB_BACKEND"] = "sqlite"
```

---

### `KeyError: 'logged_in'` in `test_login_flow`

**Cause:** Accessing `app.session_state["logged_in"]` before `State.bootstrap()` runs.

**Fix:** `AppTest.from_file("streamlit_app.py").run()` triggers `State.bootstrap()`. If the test accesses session state before `.run()`, use `.setdefault()` or check after `.run()`.

---

### `AttributeError: 'AppTest' object has no attribute 'get'` on session_state

**Cause:** `AppTest.session_state` behaves like a dict but does **not** support `.get()`.

**Fix:** Use index access:
```python
# ❌ Wrong
value = app.session_state.get("key", default)

# ✅ Correct
value = app.session_state["key"] if "key" in app.session_state else default
```

---

## 8. Performance Issues

### Sidebar filters reload slowly

**Cause:** `fetch_universes()` is hitting the FastAPI endpoint on every render.

**Fix:** `ui/utils/api.py` → `fetch_universes()` is decorated with `@st.cache_data(ttl=300)`. If you've disabled caching or changed the function signature, the cache key may be stale. Restart the Streamlit server to clear it.

---

### Stock scan takes > 5 minutes

**Cause:** `yfinance` batch download is slow for large universes (Nifty 500 = 500 tickers).

**Expected timings:**

| Universe | Typical time |
|---|---|
| Nifty 50 | 30–90 seconds |
| Nifty 100 | 60–120 seconds |
| Nifty 500 | 5–10 minutes |

**Fix:** Reduce the universe size, or deploy FastAPI on a server with a faster network connection.

---

### App re-renders on every click (expensive re-runs)

**Cause:** Streamlit re-runs the entire script on every interaction. Ensure expensive computations use `@st.cache_data`.

**Pattern:**
```python
@st.cache_data(ttl=300)
def expensive_fetch(param: str) -> pd.DataFrame:
    ...
```

---

## 9. Deployment Issues

### Streamlit Cloud: app sleeps after deployment

**Cause:** Streamlit Cloud free tier sleeps apps with no traffic.

**Fix:** The built-in keep-alive scheduler pings the app every 30 minutes. Ensure `start_scheduler()` is called in `streamlit_app.py` (it is by default).

### Streamlit Cloud: `ModuleNotFoundError` for local packages

**Cause:** `engine/` is not on `sys.path` in the Cloud environment.

**Fix:** `streamlit_app.py` inserts it explicitly. Verify these lines are present:
```python
ROOT_DIR = Path(__file__).resolve().parent
ENGINE_DIR = ROOT_DIR / "engine"
for _p in (str(ENGINE_DIR), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
```

### Docker: `address already in use` on port 8501

**Fix:**
```bash
lsof -ti:8501 | xargs kill -9
docker compose up -d
```

---

> **Still stuck?** Open a GitHub issue with the full error traceback, your `FORTRESS_DB_BACKEND` value, and whether you're running locally or on Streamlit Cloud.
