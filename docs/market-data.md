# Market Data — Developer Reference

Fortress uses a layered market data system. **All price data flows through
`engine/utils/market_data_provider.py`** — callers never import yfinance or
INDstocks directly.

---

## Provider Priority

```
INDSTOCKS_CLIENT_ID + INDSTOCKS_MPIN + INDSTOCKS_TOTP_SECRET set?
    YES → generate token via TOTP → INDstocks primary
    NO  → INDSTOCKS_TOKEN set?
              YES → INDstocks primary (static token, expires 24 h)
              NO  → yfinance only
```

On any 403 (expired token), the client auto-refreshes via TOTP and retries once.

---

## Using Market Data in Code

```python
from engine.utils.market_data_provider import get_ltp, get_ohlcv, get_batch_ltp

# Single LTP — INDstocks → yfinance fallback
price = get_ltp("RELIANCE.NS")              # float | None

# Historical OHLCV (daily) — INDstocks → yfinance fallback
df = get_ohlcv("RELIANCE.NS", "1y")         # pd.DataFrame: Open/High/Low/Close/Volume

# Batch LTP (INDstocks single call → yfinance per-symbol fallback for misses)
prices = get_batch_ltp(["RELIANCE.NS", "TCS.NS", "INFY.NS"])  # dict[str, float | None]

# Batch OHLCV (INDstocks historical endpoint, chunked; no fallback baked in —
# caller decides what to do with symbols missing from the result dict)
from engine.utils.market_data_provider import get_batch_ohlcv
frames = get_batch_ohlcv(["RELIANCE.NS", "TCS.NS", "INFY.NS"], period="1y")
# → {"RELIANCE.NS": <DataFrame>, "TCS.NS": <DataFrame>, "INFY.NS": <DataFrame>}
# Symbols INDstocks couldn't resolve/return candles for are simply absent —
# fetch those from yfinance instead of assuming full coverage.

# Check which provider is active
from engine.utils.market_data_provider import provider_status
print(provider_status())
# → {"primary": "indstocks", "primary_label": "INDmoney", "fallback": "yfinance",
#    "auth_mode": "totp", "indstocks_token_set": "True"}
```

### Rules

- ✅ Import from `market_data_provider` in routers, scanner logic, services.
- ❌ Do **not** `import yfinance as yf` in routers or scanner logic.
- ❌ Do **not** call `INDstocksClient` directly outside `market_data_provider.py`.
- ❌ Do **not** call `InstrumentsCache` directly in business logic.

---

## Supported Periods

Periods are passed as yfinance-style strings. INDstocks supports daily candles up to 1 year.

| Period | INDstocks | yfinance |
|---|---|---|
| `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y` | ✅ | ✅ |
| `2y`, `5y` | ❌ → falls back | ✅ |
| Intraday (`5m`, `1h`, etc.) | ❌ → falls back | ✅ |

---

## Batch vs Single Calls

| Scenario | Use |
|---|---|
| Single symbol, daily OHLCV | `get_ohlcv(symbol, period)` |
| Single symbol LTP | `get_ltp(symbol)` |
| Multiple symbols LTP | `get_batch_ltp([...])` — uses INDstocks batch endpoint |
| Multiple symbols OHLCV (screener bulk) | `get_stock_data(tickers, group_by="ticker")` in `stock_scanner/logic.py` — INDstocks batch historical → yfinance grouped download |

The screener's bulk scan (`get_stock_data` with `group_by="ticker"`) tries
`market_data_provider.get_batch_ohlcv()` first, which resolves every symbol
to a scrip code and fetches historical candles from INDstocks in chunks of
**5 scrip codes per call** (`_BATCH_CHUNK_SIZE`). This limit was found
empirically, not documented by INDstocks: a live probe against the real API
showed 5-code batches succeed and 6+-code batches fail with a generic
`{"debug_info":"Invalid scrip codes","message":"Bad Request"}` that gives no
hint it's actually a size cap (every code in a "bad" batch works fine when
requested solo). This is a much smaller cap than the 1000/call the
LTP/quote endpoints document, so a full universe scan still needs many
sequential calls — e.g. Nifty Smallcap 250 needs ~50 calls at 5 each — but
that's still far fewer, and far less flaky, than one yfinance request per
ticker.

`get_batch_ohlcv()` only uses the INDstocks result if **every** requested
symbol came back — this keeps a single scan on one provider instead of
silently mixing INDstocks and yfinance rows for the same run. If even one
symbol is missing (not in the instruments cache, delisted, no candles for
the period, etc.) the whole batch falls back to
`yf.download(tickers, group_by="ticker")`, same as before.

---

## Instruments Cache

The instruments cache maps NSE tickers to INDstocks security IDs.

```python
from engine.utils.instruments_cache import get_instruments_cache

cache = get_instruments_cache()
cache.get_security_id("RELIANCE.NS")   # "2885"
cache.get_scrip_code("RELIANCE.NS")    # "NSE_2885"
cache.search_symbol("HDFC")           # list of matching instruments
```

- Downloaded once per calendar day from `GET /market/instruments?source=equity`.
- Cached in `/tmp/fortress_instruments/instruments_equity_YYYY-MM-DD.csv`.
- Auto-loaded on first lookup; survives process restarts within the same day.
- Strips `.NS` / `.BO` suffixes automatically.
- **22,592 NSE equity rows** as of August 2026.

---

## INDstocks Client (internal)

The client is in `engine/utils/indstocks_client.py`. Do not use it directly in
business logic — use `market_data_provider` instead.

### Covered endpoints

| Method | INDstocks endpoint | Notes |
|---|---|---|
| `get_ltp([scrip_codes])` | `GET /market/quotes/ltp` | Up to 1000 scrips per call |
| `get_full_quote([scrip_codes])` | `GET /market/quotes/full` | OHLC, volume, depth |
| `get_historical([codes], interval, start_ms, end_ms)` | `GET /market/historical/{interval}` | Max 1 year for daily; **max 5 scrip codes per call** (undocumented, found by live probe — see "Batch vs Single Calls" above) |
| `get_instruments(source)` | `GET /market/instruments` | Returns CSV bytes |
| `get_option_chain(...)` | `GET /market/option-chain` | Full chain with greeks |
| `get_profile()` | `GET /user/profile` | Token validation |

### Rate limits

| API category | Limit |
|---|---|
| Data / Quote APIs | 5 req/s, 100 000/day |
| Order APIs | 10 req/s (not yet used) |

The client enforces a **0.2 s minimum gap** between requests automatically.

### Scrip code format

```python
"NSE_2885"    # = EXCHANGE_SECURITY_ID
"BSE_500325"  # BSE equivalent
```

Build with: `INDstocksClient.build_scrip_code("NSE", "2885")` → `"NSE_2885"`

---

## Token Management

### TOTP auto-refresh (recommended)

```bash
export INDSTOCKS_CLIENT_ID=dX03OgVqr0Cgc8x7fJQ0
export INDSTOCKS_MPIN=<your_mpin>
export INDSTOCKS_TOTP_SECRET=<base32_setup_key>
```

The client generates a token on startup using `pyotp.TOTP(secret).now()` +
`POST /generate/token`. On any 403, it refreshes and retries automatically.

### Static token (fallback)

```bash
# One-shot refresh
python3 scripts/refresh_indstocks_token.py --write-env
source .env.local

# Or set directly
export INDSTOCKS_TOKEN=eyJ...
```

Static tokens expire every 24 hours.

---

## Adding a New Data Source

1. Create `engine/utils/<source>_client.py` following the same pattern as `indstocks_client.py`.
2. Add the fallback chain to `market_data_provider.py` (after INDstocks, before yfinance).
3. Update this document and `CLAUDE.md` with the new provider rules.
4. Mock the new client in unit tests — no live API calls in tests.
