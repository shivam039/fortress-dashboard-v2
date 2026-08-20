# Deployment Guide — Fortress Dashboard

> This guide covers every supported deployment target: Streamlit Cloud (recommended), Docker / self-hosted VPS, and local development.

---

## Table of Contents

1. [Streamlit Cloud (Recommended)](#1-streamlit-cloud-recommended)
2. [Docker / Self-hosted](#2-docker--self-hosted)
3. [Database Setup (Neon Postgres)](#3-database-setup-neon-postgres)
4. [FastAPI Backend](#4-fastapi-backend)
5. [Telegram Scheduler](#5-telegram-scheduler)
6. [Environment Variables Reference](#6-environment-variables-reference)
7. [Health Checks](#7-health-checks)

---

## 1. Streamlit Cloud (Recommended)

Streamlit Cloud can run the entire app — including the in-process scan engine — without a separate FastAPI process. FastAPI is only needed for long-running MF background jobs; the Streamlit app falls back to an in-process thread when FastAPI is unreachable.

### Steps

**1.1  Push to GitHub**

```bash
git remote add origin https://github.com/your-org/fortress-dashboard
git push -u origin main
```

**1.2  Create a new app on [share.streamlit.io](https://share.streamlit.io)**

- Repository: `your-org/fortress-dashboard`
- Branch: `main`
- Main file: `streamlit_app.py`

**1.3  Set Secrets**

In the Streamlit Cloud app settings → **Secrets**, paste:

```toml
[connections.neon]
url = "postgresql://user:pass@host/dbname?sslmode=require&channel_binding=require"
```

**1.4  Set Environment Variables**

In the app settings → **Advanced** → **Secrets** (or use the Secrets UI for env vars):

```toml
FORTRESS_APP_USERNAME = "admin"
FORTRESS_APP_PASSWORD = "yourStrongPassword"
FORTRESS_DB_BACKEND = "neon"
TELEGRAM_BOT_TOKEN = "your-bot-token"
TELEGRAM_CHAT_ID = "677141544"
```

**1.5  Deploy**

Click **Deploy**. The app will start in ~60 seconds.

> **Note:** Streamlit Cloud sleeps inactive apps after ~1 week of inactivity. The built-in keep-alive scheduler (`engine/scripts/scheduler.py`) pings the app to prevent sleeping.

---

## 2. Docker / Self-hosted

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

The engine already ships with a `Dockerfile` in `engine/`:

```bash
cd engine
docker build -t fortress-api .
docker run -p 8000:7860 \
  -e DATABASE_URL="postgresql://..." \
  -e FORTRESS_DB_BACKEND=neon \
  fortress-api
```

### Docker Compose (both services)

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
    restart: unless-stopped

  app:
    build:
      context: .
      dockerfile: Dockerfile.streamlit
    ports: ["8501:8501"]
    environment:
      FORTRESS_API_URL: http://api:8000
      FORTRESS_APP_PASSWORD: ${FORTRESS_APP_PASSWORD}
      FORTRESS_DB_BACKEND: neon
      DATABASE_URL: ${DATABASE_URL}
    depends_on: [api]
    restart: unless-stopped
```

```bash
# Copy and fill in your secrets
cp .env.example .env
docker compose up -d
```

---

## 3. Database Setup (Neon Postgres)

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

## 4. FastAPI Backend

The FastAPI server (`engine/main.py`) provides:

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
python3 engine/main.py
# Starts on http://127.0.0.1:8000 by default
```

### The Streamlit app works without FastAPI

If FastAPI is unreachable, `ui/utils/api.py` detects the `ConnectionError` and the relevant views fall back to running the engine **in-process** inside Streamlit. This means:

- Stock scans run in-process (no separate server needed)
- MF jobs run in a background daemon thread
- Only features that *require* a persistent server process (e.g., server-push notifications) are unavailable

---

## 5. Telegram Scheduler

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

## 6. Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `FORTRESS_APP_USERNAME` | No | `admin` | Login username |
| `FORTRESS_APP_PASSWORD` | **Yes (prod)** | `fortress123` | Login password |
| `FORTRESS_APP_FULL_NAME` | No | `Fortress Admin` | Admin display name |
| `FORTRESS_APP_EMAIL` | No | `admin@fortress.local` | Admin email |
| `FORTRESS_APP_PHONE` | No | `+91 99999 99999` | Admin phone |
| `FORTRESS_APP_STATUS` | No | `Active` | Admin account status |
| `FORTRESS_DB_BACKEND` | No | `neon` | `neon` or `sqlite` |
| `DATABASE_URL` | Neon only | — | Neon PostgreSQL connection string |
| `NEON_CONNECTION_STRING` | Neon only | — | Alternative to `DATABASE_URL` |
| `FORTRESS_API_URL` | No | `http://127.0.0.1:8000` | FastAPI backend URL |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | No | — | Default broadcast chat ID |

---

## 7. Health Checks

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

### Database

```bash
# SQLite
ls -lh fortress_history.db

# Neon — check via engine health check
python3 engine/health_check.py
```
