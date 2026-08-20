# Fortress Engine

The `engine/` package contains the FastAPI backend and the analysis logic that
drives the Fortress frontend.

## Responsibilities

- Authentication and session-backed user profile endpoints
- Stock scanner and conviction scoring
- Mutual fund analysis and background jobs
- Options chain loading and strategy scanning
- Commodities analysis
- Shared database helpers

## Run Locally

```bash
cd /Users/shivamdixit/Desktop/fortress-dashboard-main
source .venv/bin/activate
export FORTRESS_DB_BACKEND=sqlite
export FORTRESS_APP_PASSWORD=fortress123
uvicorn engine.main:app --host 0.0.0.0 --port 8000
```

## Main Modules

- `main.py` - FastAPI app and HTTP routes
- `auth_utils.py` - JWT and cookie helpers
- `stock_scanner/` - conviction scanner and market pulse logic
- `mf_lab/` - mutual fund workflows and background jobs
- `options_algo/` - options chain and strategy logic
- `commodities/` - commodities conviction data
- `utils/db.py` - SQLite/Neon persistence helpers

## Data Notes

- The scanner and options modules still use `yfinance` as their current market
  data source.
- Some endpoints fall back to synthetic or cached data when Yahoo data is
  incomplete.
- Scan history is stored in the shared scan tables, and the frontend reads from
  those tables through FastAPI routes.

## Testing

```bash
PYTHONPATH=.:engine .venv/bin/pytest -v
```

