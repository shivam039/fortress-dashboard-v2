# FORTRESS-P1 — End-to-End Scan Performance Profile

Profiling only. No production code was changed and no scoring behaviour was
touched by this story.

## Scope & method

The scan path traced was: frontend scan request → `POST /api/scan`
(`engine/main.py:272`) → `TICKER_GROUPS` universe lookup → market regime
fetch → `prefetch_metadata()` → `get_stock_data()` batch OHLCV fetch → the
per-ticker loop calling `check_institutional_fortress()` (indicator calc +
scoring inputs) → `apply_advanced_scoring()` → `_persist_scan_history()`
(DB write) → `_sanitize_json_value(...).to_dict()` serialization → JSON
response → frontend render.

**This sandbox has no `INDSTOCKS_*` credentials and no outbound network
access to Yahoo Finance/INDstocks.** Per rule 10 (do not invent market data
or performance numbers), the network-bound stages — market-data retrieval
and metadata prefetch — are **not** reported as timed wall-clock numbers.
Instead they're analyzed as **request counts read directly from the
source** (call sites cited below), which is measurable fact, not a guess.

The CPU-bound / local-I/O stages — indicator calculation, scoring,
serialization, and DB read/write — **were** benchmarked by running the real
production functions (`stock_scanner.logic.apply_advanced_scoring`, the
same `pandas_ta` indicator calls used in `check_institutional_fortress`,
`utils.db.register_scan`/`save_scan_results`, and `main.py`'s
`_sanitize_json_value`) against synthetic OHLCV/scan-row data of the
requested sizes (50/100/250/500), median of 5 runs, on a local SQLite DB.
Harness: `bench.py` (scratch, not committed — see Appendix for how to
reproduce).

## 1. Baseline timing table (measured)

| N (tickers) | Indicator calc (ms, total) | Scoring (ms) | Serialization (ms) | DB write (ms) | Measured CPU/local total |
|---:|---:|---:|---:|---:|---:|
| 50  |   563 |  40 |  6 | 10 | ~0.62s |
| 100 | 1,042 |  40 |  9 | 11 | ~1.10s |
| 250 | 2,807 |  49 | 19 | 21 | ~2.90s |
| 500 | 5,779 |  54 | 39 | 36 | ~5.91s |

Indicator calculation scales linearly at **~11.5ms/ticker**, confirming it's
purely CPU-bound (one ticker's technical-indicator math is independent of
every other ticker's). Scoring, serialization, and DB write are all
**sub-100ms even at N=500** — none of them are meaningful bottlenecks.

Not in this table (unmeasured, see §3/§4): market-data retrieval and
metadata prefetch. Both are network-bound and, unlike every row above, are
not O(local CPU) — they are O(number of HTTP calls × real-world latency to
Yahoo Finance / INDstocks), which structural analysis (below) shows can
reach into the **thousands of sequential requests** for a cold-cache
500-ticker scan.

## 2. Where the time actually goes (traced call graph)

```
POST /api/scan  (engine/main.py:272)
 ├─ get_current_regime()                    [main.py:292]   — fixed cost, ~1 bulk yfinance call, not N-scaling
 ├─ prefetch_metadata(tickers)               [main.py:326]   — 1 batched DB read (bulk_fetch_metadata)
 ├─ get_stock_data(tuple(tickers), ...)      [main.py:331]   — batch OHLCV (bhavcopy → INDstocks → yfinance)
 └─ for ticker in tickers:                   [main.py:337]   — SERIAL, one ticker at a time, single thread
     ├─ check_institutional_fortress(ticker, hist, ...)
     │   ├─ ta.ema/rsi/atr(14)/atr(100)/adx/supertrend   — measured: ~11.5ms/ticker CPU
     │   ├─ _get_ticker_news/_get_ticker_info/_get_ticker_calendar/_get_ticker_earnings_dates(ticker)
     │   │   └─ on cache miss: _ensure_metadata_loaded()  — 4 sequential yfinance calls + 1 DB upsert
     │   └─ _get_benchmark_series(NIFTY_SYMBOL)            — cached after first ticker, ~free after that
     └─ (append to results)
 ├─ apply_advanced_scoring(score_df)          — measured: 40-54ms total, all N
 ├─ _persist_scan_history(score_df)           — measured: 10-36ms total, all N (register_scan + executemany)
 └─ _sanitize_json_value(...).to_dict(...)    — measured: 6-39ms total, all N
```

## 3. Top 5 bottlenecks, ranked by suspected cumulative wall time

1. **Per-ticker metadata cache misses (`_ensure_metadata_loaded`,
   `engine/stock_scanner/logic.py:410-464`).** On a cache miss this fires
   4 sequential, blocking `yfinance` calls (`.info`, `.news`, `.calendar`,
   `.earnings_dates`) per ticker, entirely inside the single-threaded scan
   loop. `prefetch_metadata()` (main.py:326) mitigates this only for
   tickers with a DB cache entry younger than 12h — the first scan of the
   day, a new listing, or any universe not scanned recently pays the full
   cost. At N=500 with a cold cache that's up to **2,000 sequential
   external HTTP calls** before the loop can finish — almost certainly the
   single largest wall-clock cost in the whole pipeline, an order of
   magnitude above everything measured in §1 combined.
2. **Market-data batch-fetch fallback path
   (`engine/main.py:340-349`, `stock_scanner/logic.py:230-264`).** When the
   tiered batch fetch (Bhav Copy → INDstocks → yfinance gap-fill) doesn't
   fully cover the universe, `main.py` falls back to fetching tickers
   **one at a time**, and `get_stock_data`'s own yfinance fallback retries
   3× per ticker with `1s`/`2s` sleeps on failure
   (`stock_scanner/logic.py:231-263`). Under any provider degradation this
   turns into tens of seconds of pure sleep before the 80%-failure circuit
   breaker (main.py:312-313) even trips.
3. **Indicator calculation (measured, real cost: ~11.5ms/ticker, ~5.8s at
   N=500).** Purely CPU-bound and linear in N. Profiling
   (`cProfile`, see Appendix) shows `atr()` (called twice — 14-period and
   100-period) and `adx()` dominate; both independently recompute
   `true_range`/directional-movement smoothing from scratch
   (`pandas_ta_classic`'s `atr→true_range→rma` and `adx`'s own internal
   smoothing), i.e. duplicated work *within a single ticker's own
   calculation*, not just across tickers.
4. **No concurrency anywhere in the scan loop.** `main.py:337`'s
   `for ticker in tickers:` is strictly serial — indicator calc, metadata
   fallback calls, and per-ticker exception handling all run on one
   thread. Every per-ticker cost in §3.1-§3.3 is additive across the whole
   universe rather than bounded by the slowest ticker, which is what makes
   items 1 and 2 scale so badly with N.
5. **Per-cache-miss metadata DB upserts
   (`upsert_ticker_metadata_cache`, `stock_scanner/logic.py:436`).** Unlike
   `save_scan_results` (a single batched `executemany`,
   `utils/db.py:2236`) or `bulk_fetch_metadata` (a single batched `IN`
   query), each metadata cache-miss ticker writes back with its own
   individual DB round trip — N round trips instead of 1 whenever the
   12h cache is cold.

Scoring, serialization, and scan-history persistence (items that *are*
directly comparable across N in §1) are not on this list — they're
consistently two to three orders of magnitude cheaper than the network-
bound stages above.

## 4. Request amplification analysis

Counts below are read directly from the call sites, per scan, as a
function of universe size N:

| Stage | Warm-cache / healthy provider | Cold-cache / worst case |
|---|---|---|
| Market regime (`get_current_regime`) | 1 bulk yfinance call (fixed, not N-scaling) | same |
| Metadata prefetch (`prefetch_metadata`) | 1 batched DB query (`bulk_fetch_metadata`, single `IN (...)`) | same |
| Batch OHLCV (`get_batch_ohlcv`) | 1 DB query (Bhav Copy) | `ceil(N/5)` INDstocks calls (5-symbol chunks, `market_data_provider.py:521`) + 1 yfinance gap-fill call; full per-ticker yfinance fallback (N calls × up to 3 retries) only if the batch path fails outright |
| Per-ticker metadata (`.info`/`.news`/`.calendar`/`.earnings_dates`) | 0 external calls (served from the DB cache prefill) | **4N** sequential yfinance calls (e.g. 2,000 at N=500) |
| Per-ticker metadata DB writes | 0 | N individual `UPSERT` round trips |
| Scan-result persistence | 1 `INSERT` (`register_scan`) + 1 batched `executemany` (`save_scan_results`) | same — does not scale with cache state |

The metadata path is the one genuinely N-amplifying stage with no batching
at all today: reads are batched (`bulk_fetch_metadata`), but a miss falls
through to N independent, sequential, 4-calls-each fetches with no
concurrency and no batched write-back.

## 5. Recommendations (ranked, not implemented — profiling story only)

| # | Recommendation | Impact | Complexity | Risk |
|---|---|---|---|---|
| 1 | Fetch metadata cache misses concurrently (bounded thread pool / async), instead of serially inside the scan loop | High — directly attacks the largest suspected bottleneck (§3.1) | Medium — `_INFO_CACHE` etc. already use a `Lock` (`logic.py:315`), but yfinance rate limits need a bounded pool | Medium — must not exceed Yahoo's rate limits or the existing INDstocks 5 req/s cap (documented in `engine/CLAUDE.md`) |
| 2 | Proactively warm/refresh the `ticker_metadata` cache via a scheduled job (a cron pattern already exists — `engine/cron_stock_scan.py`) so scans rarely hit a cold cache | High — turns the worst case in §4 into the warm case for most real scans | Low-Medium | Low |
| 3 | Batch the per-ticker metadata upserts the same way `save_scan_results` already batches result writes (`executemany`) | Medium — removes N individual DB round trips | Low | Low |
| 4 | Share the `true_range`/smoothing computation across `atr(14)`, `atr(100)`, and `adx()` per ticker, or compute the technical block in one vectorized pass | Medium — profiling (§3.3) shows this is a meaningful share of the measured 5.8s at N=500 | Medium | Low-Medium — must preserve `SCORING.md` semantics exactly; explicitly out of scope for this story |
| 5 | Add bounded concurrency to the per-ticker OHLCV fallback path (`main.py:340-349`) so a partial batch-fetch miss doesn't serialize N single-symbol fetches | Medium — only matters when the batch tier is already degraded | Medium | Medium — same rate-limit constraints as #1 |

## Limitations

- Market-data and metadata network timings are **not** wall-clock measured
  in this environment (no credentials, no egress to Yahoo/INDstocks) — §3
  and §4 rank them by request count and code structure, not by invented
  latency numbers. A follow-up profiling pass with real credentials in a
  deployment environment is needed to get actual wall-clock numbers for
  these stages and confirm the ranking in §3.
- Frontend rendering time was not profiled — the scope of measurable
  backend instrumentation for this story was the FastAPI request lifecycle
  only; a separate frontend trace (React render + fetch) would be needed.
- No production code, scoring logic, or tests were modified. The
  benchmark harness (`bench.py`) is scratch-only and was not added to the
  repository.

## Appendix — reproducing the local benchmark

The harness stubs `yfinance` (not installed in this sandbox) so
`stock_scanner.logic` imports cleanly, then calls the *real*
`apply_advanced_scoring`, the *real* `pandas_ta` indicator functions used
by `check_institutional_fortress`, and the *real* `utils.db.register_scan`/
`save_scan_results` against a throwaway local SQLite file, on synthetic
OHLCV/scan-row data (never real market data). Run with:

```bash
pip install pandas numpy sqlalchemy tenacity pandas_ta_classic
FORTRESS_DB_BACKEND=sqlite python3 bench.py
```

`cProfile` was used once against `bench_indicators(250)` to identify the
hot functions cited in §3.3 (`atr`/`true_range`/`rma`/`adx`).
