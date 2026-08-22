# Deployment Guide — Fortress 95 Pro

> Primary deployment is **FastAPI backend + Next.js frontend**.
> The legacy Streamlit app (`streamlit_app.py`) still works but is not the active UI.

---

## Table of Contents

1. [Local Development](#1-local-development)
2. [Render (Production Backend)](#2-render-production-backend)
3. [Docker / Self-hosted](#3-docker--self-hosted)
4. [Database Setup (Neon Postgres)](#4-database-setup-neon-postgres)
5. [FastAPI Backend](#5-fastapi-backend)
6. [INDstocks Market Data](#6-indstocks-market-data)
7. [Telegram Scheduler](#7-telegram-scheduler)
8. [Environment Variables Reference](#8-environment-variables-reference)
9. [Health Checks](#9-health-checks)

---

## 1. Local Development

### Backend

```bash
source .venv/bin/activate
export FORTRESS_DB_BACKEND=sqlite

# INDstocks TOTP (recommended — auto-refreshes tokens)
export INDSTOCKS_CLIENT_ID=dX03OgVqr0Cgc8x7fJQ0
export INDSTOCKS_MPIN=<your_mpin>
export INDSTOCKS_TOTP_SECRET=<base32_setup_key>

uvicorn engine.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Running without any INDstocks credentials at all

You don't need an INDstocks/IndMoney account to run the backend locally.
Every market-data call is gated behind a config check
(`market_data_provider._indstocks_available()`) *before* anything tries to
build an INDstocks client — so if none of `INDSTOCKS_TOKEN`,
`INDSTOCKS_CLIENT_ID`/`INDSTOCKS_MPIN`/`INDSTOCKS_TOTP_SECRET` are set, that
check is simply `False` and the app never attempts to construct a client at
all. Nothing crashes, nothing blocks on startup — every price/OHLCV/quote
call just goes straight to yfinance instead:

```bash
source .venv/bin/activate
export FORTRESS_DB_BACKEND=sqlite
uvicorn engine.main:app --host 0.0.0.0 --port 8000 --reload
```

You'll see `INDstocks LTP/OHLCV ... falling back to yfinance`-style log
lines (or just yfinance calls directly, with no INDstocks log lines at
all) instead of an error — that's expected. `GET /api/health` still returns
`200 OK`, and `provider_status()` (see [§9](#9-health-checks)) reports
`"primary": "yfinance"`. This is the right mode for local UI/UX work, tests,
or anything that doesn't depend on INDstocks-specific data quality —
switch on the TOTP trio only when you actually need it.

### Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
```

### Backend API docs

```
http://localhost:8000/docs
```

---

## 2. Render (Production Backend)

This is how the FastAPI backend (`engine/main.py`) is actually deployed for
this project — as a Render **Web Service**, either from the repo directly
(native Python runtime) or from `engine/Dockerfile`.

### Creating the service

1. Render dashboard → **New** → **Web Service** → connect this repo.
2. If deploying natively (no Docker): set **Root Directory** to `engine`,
   **Build Command** to `pip install -r requirements.txt`, and **Start
   Command** to `uvicorn main:app --host 0.0.0.0 --port $PORT`.
   - Render assigns the port dynamically via the `PORT` env var (default
     `10000`) — the app **must** bind to `$PORT`, not a hardcoded port.
     Render says it can *usually* auto-detect a fixed port instead, but
     that's not guaranteed, and a failed auto-detect fails the whole
     deploy — reading `$PORT` explicitly is the reliable path.
   - `engine/Dockerfile` hardcodes `--port 7860` (it was written for
     Hugging Face Spaces, a different host with its own convention) — if
     you deploy that Dockerfile as-is on Render, change its `CMD` to
     `uvicorn main:app --host 0.0.0.0 --port $PORT` first, or Render's
     auto-detection has to correctly find port 7860 for the deploy to work.
3. Set the environment variables below in the service's **Environment**
   tab, not in a committed file.

### Managing the INDstocks token on Render

This is the part that's easy to get stuck on: locally you run
`refresh_indstocks_token.py` and manually paste a fresh `INDSTOCKS_TOKEN`
before starting the server — but that token expires every 24 hours, and
there's no one sitting at a terminal on Render to repeat that daily.

Use the **TOTP trio** instead of the static token — it's not a fallback
for Render, it's the mode built for exactly this:

| Variable | Where to get it |
|---|---|
| `INDSTOCKS_CLIENT_ID` | Static client ID from the INDstocks/IndMoney developer dashboard |
| `INDSTOCKS_MPIN` | Your account MPIN |
| `INDSTOCKS_TOTP_SECRET` | The base32 setup key shown once under the TOTP QR code when you enabled API TOTP auth (same "can't scan? enter this key" flow as any authenticator app) |

Add all three as environment variables on the Render service (**Environment**
tab → **Add Environment Variable**) and **do not** set `INDSTOCKS_TOKEN**
there at all. With the trio present, `engine/utils/indstocks_client.py`:

- generates a fresh token itself on process startup (so every Render
  deploy/restart starts already authenticated — no manual step), and
- auto-refreshes on any `403 TokenException` mid-run and retries the
  request once, entirely inside the running process.

That's the whole mechanism — no cron job, no separate refresh service, no
webhook. The token becomes something the app manages, not something you
hand it.

**Security note:** Render doesn't have a separate "mark as secret" toggle
for individual env vars — every value in the Environment tab is already
masked by default (shown as dots, revealed only via the eye icon to
someone with dashboard access), and that's the full protection Render
offers at the per-variable level. There's nothing extra to enable for
`INDSTOCKS_MPIN` and `INDSTOCKS_TOTP_SECRET` — just make sure only people
who need account-equivalent access have access to this Render service's
dashboard, since together those two values are equivalent to full API
access to your account. (Render's separate **Secret Files** feature is for
uploading whole plaintext files like a private key or `.env`, mounted at
`/etc/secrets/<filename>` — not needed here for simple string values.)
Never put them in a committed `.env` file; `.env` and `.env.local` are
already gitignored in this repo for that reason.

### Required security env vars on Render

Three secrets in this codebase have hardcoded dev-only defaults, meant
purely so a fresh local checkout runs with zero setup. **Those same
defaults are public in this repo's git history**, so leaving any of them
unset on Render is a real, exploitable vulnerability — not a
theoretical one — because anyone who reads the source knows the exact
fallback values. Set all three before (or immediately after) your first
production deploy:

| Variable | Why it matters if left unset |
|---|---|
| `FORTRESS_JWT_SECRET` | Signs every login session token. Left unset, the app signs with the hardcoded string `fortress-dev-jwt-secret-change-in-production-2024` — anyone can forge a valid JWT for any user, including `admin`, without ever logging in. Generate with `openssl rand -hex 32`. |
| `FORTRESS_APP_PASSWORD` | The admin account's password. Left unset, it's `fortress123` — publicly known from this repo. Set this to a real password (and consider setting `FORTRESS_APP_USERNAME` to something other than `admin` too). |
| `FORTRESS_API_KEY` | See [§6 above](#6-indstocks-market-data) — without it, every API endpoint is reachable with no authentication at all from outside your own frontend. Generate with `openssl rand -hex 32`. |

The app starts and runs fine with none of these set — that's intentional,
so local dev never needs configuration — but it logs a `WARNING` for each
one that's missing. If you see any of these warnings in your **Render**
logs, treat it as a live security gap, not a cosmetic note:

```
WARNING:fortress.auth:FORTRESS_JWT_SECRET is not set — using the hardcoded dev default...
WARNING:fortress.routers.auth:FORTRESS_APP_PASSWORD is not set — the admin account falls back...
WARNING:fortress-api:FORTRESS_API_KEY is not set — FastAPI endpoints are unauthenticated...
```

### Frontend on Render (if also hosted there)

If the Next.js frontend is a separate Render service, point it at the
backend with:

```
NEXT_PUBLIC_API_URL=https://<your-backend>.onrender.com
BACKEND_URL=https://<your-backend>.onrender.com
```

---

## 3. Docker / Self-hosted

### Prerequisites

- Docker 24+ or Docker Compose 2+
- A Neon Postgres database (or PostgreSQL 15+)
- A domain name (optional but recommended for HTTPS)

### Streamlit App

```dockerfile
# Dockerfile.streamlit  (create at repo root)
FROM python:3.13-slim

WORKDIR /app
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8501
HEALTHCHECK CMD curl -f http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### FastAPI Backend

The engine already ships with a `Dockerfile` in `engine/` (written for
Hugging Face Spaces — hardcodes port 7860; adjust `CMD` to use `$PORT` if
deploying this image to a host like Render that assigns its own port):

```bash
cd engine
docker build -t fortress-api .
docker run -p 8000:7860 \
  -e DATABASE_URL="postgresql://..." \
  -e FORTRESS_DB_BACKEND=neon \
  fortress-api
```

### Docker Compose (API + frontend)

```yaml
# docker-compose.yml
version: "3.9"
services:
  api:
    build:
      context: ./engine
    ports: ["8000:7860"]
    environment:
      DATABASE_URL: ${DATABASE_URL}
      FORTRESS_DB_BACKEND: neon
      # INDstocks TOTP auto-refresh
      INDSTOCKS_CLIENT_ID: ${INDSTOCKS_CLIENT_ID}
      INDSTOCKS_MPIN: ${INDSTOCKS_MPIN}
      INDSTOCKS_TOTP_SECRET: ${INDSTOCKS_TOTP_SECRET}
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://api:8000
    depends_on: [api]
    restart: unless-stopped
```

```bash
# Copy and fill in your secrets
cp .env.example .env
docker compose up -d
```

---

## 4. Database Setup (Neon Postgres)

Fortress supports two database backends:

| Backend | When to use |
|---|---|
| **Neon** (PostgreSQL) | Production, Streamlit Cloud |
| **SQLite** | Local development, CI, testing |

### Neon (Production)

1. Create a free project at [neon.tech](https://neon.tech)
2. Copy the **pooled connection string** from the Neon dashboard
3. Set `DATABASE_URL` to this string in your environment / Streamlit secrets
4. Set `FORTRESS_DB_BACKEND=neon`

The `engine/utils/db.py` → `init_db()` function creates all tables automatically on first startup. No manual migrations are needed.

### SQLite (Local Development)

```bash
export FORTRESS_DB_BACKEND=sqlite
streamlit run streamlit_app.py
```

A `fortress_history.db` file is created at the repository root. This file is gitignored.

---

## 5. FastAPI Backend

The FastAPI server (`engine/main.py`) is the production backend for the Next.js UI.

### Key endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/api/universes` | GET | List available stock universes |
| `/api/scan` | POST | Run a full stock scan |
| `/api/sector-pulse` | GET | Sector regime & momentum data |
| `/api/mf-analysis` | GET | Mutual fund analysis results |
| `/api/commodities` | GET | Commodity prices |
| `/mf/trigger-job` | POST | Trigger a background MF job |

### Running locally

```bash
source .venv/bin/activate
export FORTRESS_DB_BACKEND=sqlite
export INDSTOCKS_CLIENT_ID=dX03OgVqr0Cgc8x7fJQ0
export INDSTOCKS_MPIN=<your_mpin>
export INDSTOCKS_TOTP_SECRET=<base32_setup_key>
uvicorn engine.main:app --host 0.0.0.0 --port 8000 --reload
```

Or without any INDstocks vars at all to run yfinance-only — see
[§1](#1-local-development).

### Market data

All price data flows through `engine/utils/market_data_provider.py`. Do not call
yfinance or `INDstocksClient` directly from routers or scanner logic.

---

## 6. INDstocks Market Data

INDstocks is the primary market data source for NSE equities. yfinance is the automatic fallback.

### TOTP auto-refresh (recommended — required on Render, see §2)

Set all three variables — the engine generates and refreshes tokens automatically:

```bash
export INDSTOCKS_CLIENT_ID=dX03OgVqr0Cgc8x7fJQ0
export INDSTOCKS_MPIN=<your_mpin>
export INDSTOCKS_TOTP_SECRET=<base32_setup_key_from_dashboard_qr>
```

### Static token (fallback, local dev only)

Tokens expire every 24 hours. Refresh with:

```bash
python3 scripts/refresh_indstocks_token.py --write-env
source .env.local
```

This mode is fine for a local terminal you restart daily, but doesn't work
unattended — there's no one to re-run the script on a server. Use the TOTP
trio for anything long-running (Render, Docker, any always-on process).

### No INDstocks account yet

Set none of the above. Market data falls back to yfinance for everything —
see [§1](#1-local-development) for details on exactly why that's safe (no
crash, no manual flag needed).

### Instruments cache

The NSE equity instruments CSV is downloaded once per calendar day and cached in `/tmp/fortress_instruments/`.
Use `instruments_cache.get_scrip_code("RELIANCE.NS")` → `"NSE_2885"` for symbol lookups.

### Credential safety — what does and doesn't get logged

Audited `engine/main.py` and `engine/utils/indstocks_client.py` for this:

- `main.py` never references `INDSTOCKS_MPIN`, `INDSTOCKS_TOTP_SECRET`, or
  `INDSTOCKS_TOKEN` directly, and its global exception-handling middleware
  (`catch_exceptions_middleware`) logs full tracebacks **server-side only**
  — an HTTP client only ever sees a generic `{"error": "...", "error_id":
  "..."}`, never a traceback or exception message.
- `provider_status()` (the function backing the `/api/market-data/status`
  endpoint the frontend's `SystemStatus` badge polls) only returns booleans
  and labels (`"auth_mode": "totp"`, `"indstocks_token_set": "True"`) —
  never the token, MPIN, or TOTP secret value itself.
- `indstocks_client.py`'s own log lines (`"Requesting new INDstocks token
  via TOTP..."`, `"403 TokenException — attempting auto-refresh..."`,
  `"Token refresh failed: %s"`) never interpolate the MPIN, TOTP code, or
  token — only status/outcome strings, or (on a failed refresh) the
  *response* INDstocks itself sent back, not what we sent it.
- The one residual, low-probability risk: if INDstocks' own `/generate/token`
  endpoint ever echoed the submitted MPIN/TOTP code back inside an error
  message (well-designed auth APIs don't, but it's not something this repo
  controls), that response text would end up in the server-side log stream
  (e.g. Render's log viewer) via the "Token refresh failed" log line. This
  isn't client-exposed and a TOTP code is only valid for ~30 seconds, but
  it's worth knowing it's the one spot that isn't fully redacted.

---

## 7. Telegram Scheduler

The built-in scheduler (`engine/scripts/scheduler.py`) runs two background threads:

| Thread | Purpose | Default time |
|---|---|---|
| **Telegram broadcast** | Sends daily stock tips to subscribers | 09:45 IST |
| **Keep-alive pinger** | Pings the Streamlit app to prevent cloud sleep | Every 30 min |

### Configuring subscribers

From the Streamlit app sidebar → **📡 Telegram Scheduler** expander, or from the **Stock Screener** → **📢 Telegram Alert Settings** expander:

```
677141544,-1003933571318
```

Subscribers are saved to `engine/scripts/telegram_subscribers.txt`.

### Manual broadcast

Click **📤 Send Broadcast Now** in the sidebar, or trigger via the API:

```bash
curl -X POST http://localhost:8000/mf/trigger-job \
  -H "Content-Type: application/json" \
  -d '{"job_type": "full_refresh", "force_refresh": true}'
```

---

## 8. Environment Variables Reference

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `FORTRESS_JWT_SECRET` | **Yes (prod)** | hardcoded dev string, public in git history — see [security note](#2-render-production-backend) | Signs all login session JWTs |
| `FORTRESS_APP_USERNAME` | No | `admin` | Login username |
| `FORTRESS_APP_PASSWORD` | **Yes (prod)** | `fortress123`, public in git history — see [security note](#2-render-production-backend) | Login password |
| `FORTRESS_APP_FULL_NAME` | No | `Fortress Admin` | Admin display name |
| `FORTRESS_DB_BACKEND` | No | `neon` | `neon` or `sqlite` |
| `DATABASE_URL` | Neon only | — | Neon PostgreSQL connection string |
| `NEON_CONNECTION_STRING` | Neon only | — | Alternative to `DATABASE_URL` |
| `FORTRESS_API_KEY` | **Yes (prod)** | — (unset = unauthenticated API) | API key for protected endpoints |
| `FORTRESS_CORS_ORIGINS` | No | — | Allowed CORS origins |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | No | — | Default broadcast chat ID |
| `PORT` | Render only | `10000` | Set automatically by Render — bind your server to this, don't hardcode a port |

### INDstocks Market Data

| Variable | Mode | Description |
|---|---|---|
| `INDSTOCKS_CLIENT_ID` | TOTP | Static client ID from dashboard |
| `INDSTOCKS_MPIN` | TOTP | Account MPIN |
| `INDSTOCKS_TOTP_SECRET` | TOTP | Base32 setup key from TOTP QR code |
| `INDSTOCKS_TOKEN` | Static | Access token — expires every 24 h |

Set the TOTP trio for automatic token management — required for any
always-on deployment (Render, Docker) since there's no one to manually
refresh a static token daily. Without any INDstocks vars, market data falls
back to yfinance; see [§6](#6-indstocks-market-data).

### Frontend

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | FastAPI base URL (defaults to `http://localhost:8000`) |
| `BACKEND_URL` | Server-side API URL |

---

## 9. Health Checks

### Streamlit

```
GET http://localhost:8501/_stcore/health
→ 200 OK
```

### FastAPI

```
GET http://localhost:8000/health
→ {"status": "ok"}
```

### INDstocks provider

```python
from engine.utils.market_data_provider import provider_status
print(provider_status())
# {"primary": "indstocks", "fallback": "yfinance", "indstocks_token_set": "True"}
```

### Database

```bash
# SQLite
ls -lh fortress_history.db

# Neon — check via engine health check
python3 engine/health_check.py
```
