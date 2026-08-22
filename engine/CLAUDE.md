# Engine Rules (Backend)

Read the root `CLAUDE.md` first. This file adds backend-specific rules.

## Endpoint Rules

- All new FastAPI endpoints go in `engine/routers/`, not in `engine/main.py`.
- Use `APIRouter` and include it in `main.py`. Keep routers thin — logic in utils/services.
- Long-running scans must use `BackgroundTasks` or a background job; never block a request > 5s.

## Market Data

- **ALWAYS use `engine/utils/market_data_provider.py`** to fetch prices/OHLCV.
  - Do not import yfinance directly in routers or scanner logic.
  - Do not call `INDstocksClient` directly in routers or scanner logic.
- `market_data_provider.py` handles provider selection, fallback, and logging.

## INDstocks Client

- `INDstocksClient` in `engine/utils/indstocks_client.py` is the only place that calls
  `https://api.indstocks.com`.
- Rate limits (from INDstocks docs):
  - Data/Quote APIs: 5 req/s, 100 000/day
  - Order APIs: 10 req/s (not used here yet)
- The client enforces a 0.2 s minimum gap between requests automatically.
- Token comes from `os.getenv("INDSTOCKS_TOKEN")` — never hardcode it.

## Instruments Cache

- `engine/utils/instruments_cache.py` downloads the NSE equity CSV once per day into `/tmp`.
- Use `instruments_cache.get_security_id("RELIANCE")` to translate NSE symbols → security IDs.
- Do not fetch instruments CSV in a hot path — it is already pre-cached at startup.

## Data Standards

- Prefer pandas over raw loops for tabular data.
- Timestamps from INDstocks are Unix epoch milliseconds (requests) / seconds (candle `ts`).
  Always convert to IST `datetime` before storing or returning to the frontend.
- NSE symbols in fortress_config use the `.NS` suffix — strip it before INDstocks lookups.

## Testing

- Tests in `tests/` — run with `PYTHONPATH=.:engine .venv/bin/pytest -v`.
- Mock `INDstocksClient` in unit tests; use `pytest-mock` or `unittest.mock`.
- Do not make live API calls in unit tests.
