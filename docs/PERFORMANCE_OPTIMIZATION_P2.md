# FORTRESS-P2 — Backend Scan Optimization

Implements the priority-ordered fixes for the bottlenecks measured in
[`PERFORMANCE_PROFILE_P1.md`](./PERFORMANCE_PROFILE_P1.md). No Fortress
scoring weights, normalization, quality gates, regime multipliers, ranking
semantics, or API response shape were changed.

## 1. P1 bottlenecks addressed

| P1 finding | Addressed? | How |
|---|---|---|
| Per-ticker metadata cache misses — up to 4N sequential yfinance calls, serial, inside the scoring loop | **Yes (Priority 1)** | `prefetch_metadata()` now fetches every DB-cache miss concurrently, with a bounded thread pool, *before* the scoring loop starts |
| Metadata cache write-back — one DB upsert per ticker | **Yes (Priority 2)** | New `upsert_ticker_metadata_cache_batch()`; the concurrent prefetch path uses it instead of looping |
| Serial scan loop | **Partially (Priority 1/3/4)** | The metadata-fetch and OHLCV-fallback-fetch portions of the loop are now concurrent; the indicator/scoring computation itself is unchanged (still per-ticker, still serial — see §11) |
| Partial OHLCV batch-fetch fallback can become serial | **Yes (Priority 4)** | Bounded-concurrency, chunked fetch, with circuit-breaker early-exit preserved |
| ATR/ADX duplicate internal computation | **Not implemented (Priority 5)** | Investigated; left unchanged per the story's own escape hatch — see §11 |

## 2. Implementation summary

**Priority 1 — metadata prefetch concurrency.** `prefetch_metadata()`
(`engine/stock_scanner/logic.py`) still does its existing single batched DB
read first. Whatever that read doesn't cover (`missing`) is now fetched live
via `_prefetch_metadata_concurrently()`, a bounded `ThreadPoolExecutor`
(default 4 workers, `FORTRESS_METADATA_FETCH_WORKERS` env var, hard-capped
at 16). Each ticker's fetch is isolated: `_fetch_metadata_live()` is a pure,
side-effect-free fetch function (no cache/DB writes), submitted per-ticker;
results are mapped back via `future_to_symbol`, not completion order.
A successful fetch calls `_store_metadata_success()`; a failed one calls
`_store_metadata_blank()` — the exact same empty-default fallback
`_ensure_metadata_loaded()` already used, so a fetch failure degrades
identically to before, just detected earlier and in parallel instead of one
ticker at a time inside the scoring loop.

`_ensure_metadata_loaded()` was refactored (not behaviorally changed) to
share `_fetch_metadata_live`/`_store_metadata_success`/`_store_metadata_blank`
with the concurrent path, and now only runs when `prefetch_metadata()` never
ran for that ticker at all, or its DB read itself failed (see its docstring
and §5 below for exactly when).

If `bulk_fetch_metadata()` (the DB read) itself raises, `prefetch_metadata()`
aborts immediately with no live-fetch attempt, matching its pre-P2 behavior
exactly — a DB outage falls back to the per-ticker lazy path rather than
firing a full-universe concurrent fetch off the read failure itself.

**Priority 2 — batch metadata persistence.** `upsert_ticker_metadata_cache_batch()`
(`engine/utils/db.py`) persists every successful concurrent fetch in one
`executemany`-style statement / one transaction (SQLAlchemy `conn.execute(text(...), list_of_dicts)`
for Neon, `sqlite3.executemany()` for SQLite), with identical upsert
semantics (`ON CONFLICT ... DO UPDATE`, `updated_at` refreshed) to the
existing single-item `upsert_ticker_metadata_cache()`, which is unchanged
and still used by the lazy single-ticker fallback.

**Priority 3 — no surprise blocking in the ticker loop.** Documented
explicitly in `_ensure_metadata_loaded()`'s docstring: after a normal
`prefetch_metadata()` call, every ticker in that scan's universe — including
ones whose live fetch failed — is already in the in-memory cache (with real
data or the blank default), so `_get_ticker_info/_news/_calendar/_earnings_dates`
inside `check_institutional_fortress()` hit the cache and never call
`_ensure_metadata_loaded`'s live path. That fallback can still fire when:
  - `prefetch_metadata()`'s own DB read failed (see above) — every ticker in
    that scan falls back to the lazy per-ticker path for that one scan;
  - a caller scores a ticker without calling `prefetch_metadata()` first at
    all (e.g. `/api/scan/search`'s single-ticker path — not `/api/scan`).

**Priority 4 — bounded-concurrency OHLCV fallback.** `main.py`'s `/api/scan`
only takes this path when the *entire* batch OHLCV fetch returns nothing
(`batch_data.empty`) — the rare, already-degraded case P1 flagged. Instead of
fetching all N tickers serially inline, it now fetches one bounded chunk at a
time (chunk size = `FORTRESS_OHLCV_FALLBACK_WORKERS`, default 4, via
`stock_scanner.logic.fetch_ohlcv_fallback_chunk()`), then runs that chunk
through the *exact same* per-ticker try/except and circuit-breaker counting
as before, before fetching the next chunk. Chunking (rather than fetching
the whole universe concurrently up front) is deliberate: it preserves the
breaker's early-exit property — once it trips, no further chunks are ever
fetched, matching the pre-P2 behavior of stopping mid-scan instead of racing
ahead of a real provider outage. `fetch_ohlcv_fallback_chunk()` takes an
injectable `fetch_fn` so `main.py` passes its own `get_stock_data` reference
(not `stock_scanner.logic`'s) — this is what the pre-P2 code called inline,
and it's what existing tests monkeypatch.

`market_data_provider.py` was not touched; no retry, precedence, or rate-limit
logic changed — only the concurrency and chunk-boundary wrapping around the
existing single-ticker `get_stock_data()` calls.

**Priority 5 — indicator duplication.** Investigated, not implemented — see
§11.

**Instrumentation.** `run_scan()` now times each stage (`metadata_prefetch_s`,
`market_data_s`, `indicator_scoring_loop_s`, `scoring_s`, `db_persist_s`,
`total_scan_s`) plus metadata cache-hit/miss/fetch-success/fetch-failure
counts, logged as one structured line (`scan_timing ...`) per scan. This is
server-side logging only — nothing was added to the HTTP response, so the
API contract is unchanged.

## 3. Files changed

- `engine/stock_scanner/logic.py` — concurrent metadata prefetch
  (`_prefetch_metadata_concurrently`, `_fetch_metadata_live`,
  `_store_metadata_success`/`_store_metadata_blank`, bounded worker-count
  helpers), bounded-concurrency OHLCV fallback helper
  (`fetch_ohlcv_fallback_chunk`, `_fetch_single_ticker_ohlcv`),
  `prefetch_metadata()` rewritten to fetch+persist misses and return a
  stats dict, `_ensure_metadata_loaded()` refactored to share the new
  fetch/store helpers.
- `engine/utils/db.py` — new `upsert_ticker_metadata_cache_batch()`.
- `engine/main.py` — `/api/scan` timing instrumentation; the OHLCV-fallback
  branch of the scan loop restructured into chunked bounded-concurrency
  fetch + the existing per-ticker scoring/breaker logic (factored into
  `_record_result`, shared by both the fallback and non-fallback branches).
- `tests/backend/test_metadata_prefetch.py` — one existing test updated for
  `prefetch_metadata()`'s intentionally-changed contract (misses are now
  live-fetched, not left for later); one new stats-dict test.
- `tests/backend/test_metadata_prefetch_concurrency.py` (new) — bounded
  concurrency, per-ticker result mapping, partial-failure isolation, batch
  persistence call.
- `tests/backend/test_metadata_cache.py` — batch-persistence tests added.
- `tests/backend/test_ohlcv_fallback_chunk.py` (new) — bounded concurrency,
  result mapping, failure isolation, default `fetch_fn`.
- `tests/backend/test_scoring_equivalence_p2.py` (new) — scoring
  equivalence across cache-population paths (see §9).
- `tests/backend/test_api.py` — one new test for fetch-level failure
  isolation + circuit-breaker preservation in the OHLCV fallback path.

## 4. Concurrency design

- **Bounded**: both pools use `ThreadPoolExecutor(max_workers=N)`, `N`
  capped at 16 and never exceeding the item count.
- **Configurable**: `FORTRESS_METADATA_FETCH_WORKERS` and
  `FORTRESS_OHLCV_FALLBACK_WORKERS` env vars (default 4 each); set to `1`
  for fully serial (pre-P2) behavior with no code change.
- **Failure-isolated**: each future is `try`/`except`-wrapped independently;
  one ticker's exception never touches another's future or aborts the pool.
- **Deterministic result mapping**: results are attributed via a
  `future_to_symbol`/`future_to_ticker` dict, not completion order — final
  cache/result state is identical regardless of which fetch finishes first
  (see `test_results_mapped_to_correct_ticker_regardless_of_completion_order`
  and `test_fetch_ohlcv_fallback_chunk_maps_results_to_correct_ticker`).
- **Compatible with existing caches/locks**: `_INFO_CACHE`/`_NEWS_CACHE`/
  `_CAL_CACHE`/`_EARN_CACHE` writes still go through the existing
  `_META_LOCK`; no new shared mutable state was introduced.

## 5. Provider/rate-limit safeguards

- Metadata pool defaults to 4 concurrent yfinance calls, not unbounded —
  conservative relative to yfinance having no documented hard cap, chosen to
  reduce burst load rather than maximize throughput.
- The OHLCV fallback pool is bounded the same way, and only activates in the
  already-degraded "whole batch fetch failed" case; it does not touch
  `market_data_provider.py`'s own INDstocks chunking (5 scrips/call) or
  rate-gating (0.2s minimum gap, enforced inside `INDstocksClient`).
- The circuit breaker's early-exit property is preserved by chunking rather
  than fetching the whole fallback universe concurrently up front (§2,
  Priority 4) — a real outage still stops issuing new requests once tripped.
- Both pools can be forced back to serial (`*_WORKERS=1`) without a code
  change if either provider proves sensitive to concurrent calls in
  practice.

## 6. Before/after measured local timings

Reproduces P1's methodology: real production functions
(`apply_advanced_scoring`, the same `pandas_ta` indicator calls used by
`check_institutional_fortress`, `register_scan`/`save_scan_results`) on
synthetic data, median of 5 runs. These stages were **not** touched by P2
(Priority 5 left unimplemented), so this is a no-regression check against
P1's numbers, not a speedup claim:

| N | Indicator calc (ms) | Scoring (ms) | Serialization (ms) | DB write (ms) |
|---:|---:|---:|---:|---:|
| 50 | 653 | 56 | 7 | 13 |
| 100 | 1,323 | 63 | 11 | 17 |
| 250 | 3,460 | 67 | 23 | 25 |
| 500 | 7,074 | 83 | 45 | 39 |

(P1's numbers on its own run: 563/1,042/2,807/5,779ms indicators,
40/40/49/54ms scoring, 6/9/19/39ms serialize, 10/11/21/36ms DB — same order
of magnitude and same linear-in-N shape; the absolute differences are
machine/load variance between sandbox sessions, not a code change, since
none of these four code paths were modified in P2.)

Metadata-prefetch and OHLCV-fallback wall-clock times were **not**
benchmarked against real providers here either — this sandbox still has no
INDSTOCKS_*/network access to Yahoo Finance (confirmed: a live `yf.Ticker`
call returns a proxy-level connection failure). See §7 for the mechanics
demonstration instead.

## 7. Mocked-network benchmark (SIMULATION — not real-provider performance)

`_fetch_metadata_live` was monkeypatched to `time.sleep(0.05)` (an assumed
constant, not measured from any real provider) to isolate and demonstrate
the concurrency *mechanics* of Priority 1's change — old serial loop vs. the
real `_prefetch_metadata_concurrently()` function, 4 workers, all-cache-miss:

| N | Old serial (ms) | New bounded-concurrent, 4 workers (ms) | Speedup |
|---:|---:|---:|---:|
| 50 | 2,510 | 656 | 3.83x |
| 100 | 5,018 | 1,280 | 3.92x |
| 250 | 12,572 | 3,170 | 3.97x |
| 500 | 25,152 | 6,289 | 4.00x |

The speedup converges to ~4x as N grows, exactly matching the theoretical
bound for 4 bounded workers (`wall_time ≈ ceil(N/4) × per_call_latency`) —
confirms the pool is real, bounded, and scales as designed. **The absolute
millisecond values are a simulation artifact of the assumed 50ms/call
latency, not a prediction of real INDstocks/yfinance response times.**

## 8. Request-count comparison

| Path | Before (worst case, N tickers) | After (worst case, N tickers) |
|---|---|---|
| Metadata external fetches | Up to 4N sequential yfinance calls, inline in the scoring loop | Same 4N total calls, issued from a bounded pool (default 4 concurrent) *before* scoring starts |
| Metadata DB write-back | Up to N individual `UPSERT` round trips | 1 batched `executemany`/transaction for all successful fetches |
| OHLCV fallback (only when the whole batch fetch fails) | N sequential single-ticker fetches, each up to 3 retries | Same N fetches, issued in bounded chunks (default 4 concurrent per chunk) |
| Scan-result persistence | 1 `INSERT` + 1 batched `executemany` (already optimal, per P1) | Unchanged — not touched (non-goal) |

## 9. Scoring-equivalence evidence

`tests/backend/test_scoring_equivalence_p2.py` populates the in-memory
metadata cache two different ways for the same deterministic OHLCV fixture
and fixed metadata — (a) a direct write (the end state a warm cache or the
pre-P2 lazy fetch would leave) vs. (b) the new concurrent
`prefetch_metadata()` path — then runs the real, unmodified
`check_institutional_fortress()` and `apply_advanced_scoring()`:

- `test_check_institutional_fortress_identical_across_cache_population_paths`:
  asserts the full result dict (`Score`, `RS_Score`, `Technical_Raw`,
  `Fundamental_Raw`, etc.) is **exactly equal** between the two paths.
- `test_apply_advanced_scoring_ranking_identical_across_cache_population_paths`:
  two tickers with different (gate-passing) fundamentals, scored via both
  paths — `pd.testing.assert_frame_equal` on `Score`/`ai_score`/`Verdict`
  passes, and the relative ranking order is identical, with a sanity check
  that the two tickers' scores actually differ (not a degenerate tie).

Both tests pass. Since P2 changed only *how* the cache gets populated, never
what `check_institutional_fortress`/`apply_advanced_scoring` compute from
it, this is direct evidence that scoring output, component scores, and
ranking are unaffected.

## 10. Tests run and results

```
PYTHONPATH=.:engine pytest tests/backend -q
248 passed, 4 warnings (pre-existing FastAPI/Starlette deprecation warnings, unrelated to this change)
```

Includes: all pre-existing backend tests (unchanged, still green — notably
`test_api.py`'s circuit-breaker-trip, no-breaker, and history-persistence
tests, which exercise the restructured `/api/scan` loop end-to-end), plus
the new/updated coverage listed in §3. `ruff check` on every changed/added
file reports no new findings.

## 11. Remaining bottlenecks

- **Indicator calculation (~11.5ms/ticker, ~7s at N=500 in this run) is
  still fully serial**, one ticker at a time, and still the largest single
  *measured* local cost. Investigated for Priority 5 (ATR-14/ATR-100/ADX
  sharing `true_range`/smoothing state): `pandas_ta_classic`'s `atr()` and
  `adx()` each compute their own internal smoothing independently with no
  public API to inject a precomputed `true_range`/Wilder-RMA series, and
  verifying exact numerical equivalence of a hand-rolled shared-computation
  replacement (same NaN handling, same warm-up-period behavior, same
  floating-point accumulation order) was not achievable with confidence
  inside this story's scope. Per the story's own instruction — "if exact
  equivalence cannot be demonstrated, leave the indicator implementation
  unchanged and document the opportunity instead" — this was left
  unimplemented. Any future attempt should ship with a test that diffs
  indicator output row-for-row against unmodified `pandas_ta_classic` across
  a range of real historical series before merging.
- **Real-provider wall-clock impact of Priority 1/4 is unverified** —
  everything in §7 is a mocked-latency simulation; a deployment with real
  INDSTOCKS_*/yfinance access should re-run `scan_timing` log analysis
  before/after to confirm the real-world speedup shape matches §7's
  mechanics.
- **The metadata DB read (`bulk_fetch_metadata`) and OHLCV batch read
  (`fetch_bhavcopy_ohlcv_batch`) are unchanged** — both were already
  single batched queries per P1, not touched here (non-goal).

## 12. Risks

- Two new env vars (`FORTRESS_METADATA_FETCH_WORKERS`,
  `FORTRESS_OHLCV_FALLBACK_WORKERS`) default to 4 — untested against real
  INDstocks/yfinance rate-limit behavior in this sandbox (no network
  access). If either provider degrades under 4 concurrent calls in
  production, set the corresponding env var to `1` to fall back to fully
  serial with no code change/redeploy of logic.
- `prefetch_metadata()`'s return value contract changed (stats dict instead
  of implicit `None`); any other caller relying on the old implicit-`None`
  return should be defensive (`prefetch_metadata(...) or {}`), as `main.py`
  now is.
- Thread-pool overhead (pool creation/teardown per chunk in the OHLCV
  fallback path) adds a small fixed cost per chunk versus a single flat
  loop; negligible next to network latency, not measured separately here.

## 13. Recommended next optimization

Per the priority ordering, indicator calculation (§11) is the next-largest
*measured* local cost once metadata/network amplification (this story's
focus) is addressed. Recommend a dedicated follow-up story scoped
specifically to proving numerical equivalence (golden-output regression
tests across real historical series) before attempting any ATR/ADX
computation sharing — not bundled into a broader change.
