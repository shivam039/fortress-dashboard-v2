# Fortress 95 Pro

Quantitative trading dashboard for Indian markets (NSE focus).
Next.js 16 frontend + FastAPI backend. **Primary UI is Next.js.**
Legacy Streamlit code in `ui/` and `engine/legacy/` is reference only — do not expand it.

## Stack

- **Frontend**: Next.js 16 (App Router), React 19, TypeScript, Recharts, lucide-react
- **Backend**: FastAPI, Python 3.9+, pandas, yfinance (being replaced as primary)
- **Database**: SQLite (local, `FORTRESS_DB_BACKEND=sqlite`) / Neon Postgres (`DATABASE_URL`)
- **Market data**: INDmoney / INDstocks (primary, when `INDSTOCKS_CLIENT_ID` + `INDSTOCKS_MPIN` + `INDSTOCKS_TOTP_SECRET`, or a static `INDSTOCKS_TOKEN`, are set) → yfinance (fallback) → cache

## Key Directories

- `frontend/src/app/` — Next.js pages (screener, mf-lab, options, etc.)
- `frontend/src/components/` — Shared UI components
- `engine/` — FastAPI app + all analysis logic
- `engine/stock_scanner/` — Conviction scoring (main logic)
- `engine/utils/` — DB, brokers, market data helpers
- `engine/utils/indstocks_client.py` — INDstocks REST client (rate-limited, retries)
- `engine/utils/instruments_cache.py` — Daily NSE instruments CSV cache + symbol→ID lookup
- `engine/utils/market_data_provider.py` — Provider abstraction (INDstocks → yfinance)
- `engine/routers/` — FastAPI routers for frontend
- `tests/` — Backend + frontend tests

## Commands

### Backend
```bash
source .venv/bin/activate
export FORTRESS_DB_BACKEND=sqlite        # local SQLite
export INDSTOCKS_CLIENT_ID=<client_id>       # enables INDmoney provider
export INDSTOCKS_MPIN=<mpin>                 # account MPIN
export INDSTOCKS_TOTP_SECRET=<totp_secret>   # base32 TOTP setup key for auto-refresh
uvicorn engine.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend
```bash
cd frontend && npm install
npm run dev      # http://localhost:3000
npm run build    # production only
```

### Tests
```bash
PYTHONPATH=.:engine .venv/bin/pytest -v
```

## Architecture Rules

1. **Next.js is the active UI.** Do not add new Streamlit features.
2. **All market data goes through `market_data_provider.py`** — never call yfinance or
   INDstocks directly from routers or scanner logic.
3. **INDstocks/INDmoney is primary, yfinance is fallback.** If neither the TOTP trio
   (`INDSTOCKS_CLIENT_ID` + `INDSTOCKS_MPIN` + `INDSTOCKS_TOTP_SECRET`) nor a static
   `INDSTOCKS_TOKEN` are set, yfinance runs automatically — no code changes needed.
4. **Prefer async FastAPI endpoints + BackgroundTasks** for long scans.
5. **Scoring logic has one doc per module — update the matching one when you
   change scores:**
   - Stock scanner: `engine/stock_scanner/logic.py` + `SCORING.md`
   - Mutual funds: `engine/mf_lab/logic.py` + `MF_SCORING.md`
   - REITs & InvITs: `engine/reit_invits/logic.py` + `REIT_INVIT_SCORING.md`
   - US Investing: `engine/us_investing/logic.py` + `US_INVESTING_SCORING.md`
6. Keep secrets in env vars. Never hardcode tokens or passwords.
7. Use type hints everywhere in Python. Strict TypeScript on frontend.

## Coding Conventions

- Python: PEP 8, type hints, Google-style docstrings on public functions.
- Prefer explicit imports. No `import *`.
- Frontend: functional components, Server Components by default.
- Small, focused changes. Do not refactor unrelated code.
- After code changes: run relevant tests or at least type-check/lint.

## Do Not

- Expand the legacy Streamlit UI.
- Call yfinance or INDstocks directly outside `market_data_provider.py`.
- Commit `.env` files, API tokens, or database files.
- Make large speculative refactors without asking first.
- Use `INDSTOCKS_CLIENT_ID`, `INDSTOCKS_MPIN`, `INDSTOCKS_TOTP_SECRET`, or `INDSTOCKS_TOKEN` in any tracked file — env vars only.
