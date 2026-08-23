# Fortress US Investing — Conviction Score Documentation

> **Primary file:** `engine/us_investing/logic.py`
> **Supporting modules:** `engine/us_investing/universe.py`, `engine/us_investing/service.py`, `engine/routers/us_investing.py`, `engine/us_investing/jobs.py`

This documents how a US stock/ETF's conviction score is actually computed
today — an accurate technical reference, following the same intent and style
as `SCORING.md`, `MF_SCORING.md`, and `REIT_INVIT_SCORING.md`: what the code
does, not what it appears to do, including where it falls short.

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [The Universe](#2-the-universe)
3. [Raw Metrics (`_compute_raw_metrics`)](#3-raw-metrics-_compute_raw_metrics)
4. [Conviction Score (`_score_universe`)](#4-conviction-score-_score_universe)
5. [Confidence & Staleness](#5-confidence--staleness)
6. [Caching](#6-caching)
7. [Known Gaps & Open Questions](#7-known-gaps--open-questions)
8. [What the UI Actually Shows](#8-what-the-ui-actually-shows)

---

## 1. Architecture Overview

```
FULL_UNIVERSE (static, 31 symbols: US stocks + ETFs)
        │
        ▼
service.get_service().fetch_single(symbol)   ── OHLCV + info, per symbol
        │
        ▼
_compute_raw_metrics()            ── per-symbol: returns, volatility, max
        │                            drawdown, P/E, beta, liquidity, risk
        │                            flags; USD→INR conversion for display
        ▼
_score_universe()                 ── CONVICTION SCORE (relative,
        │                            peer-percentile-ranked within
        │                            whatever list was just fetched)
        ▼
GET /api/us-investing             ── serves from a single in-process cache
                                      tier (§6), falls back to a live fetch
```

Architecturally the closest sibling of this module is REIT/InvIT scoring
(`REIT_INVIT_SCORING.md`) — same shape (static universe, per-symbol raw
metrics, one peer-relative weighted score, no regime multiplier, no
IQR/z-score normalization) — but with a different weight set tuned for
equities/ETFs instead of income trusts, and a notably simpler caching layer
(§6).

**No conviction label.** Unlike MF Lab and REIT/InvIT, this module never
calls `utils.conviction_engine._label()` — there is no `conviction_label`/
`conviction_emoji` field anywhere in a US Investing record. This appears
intentional rather than an oversight: the frontend page doesn't render a
`SignalBadge`-equivalent for US instruments, only `ConvictionScoreCard`
(score + breakdown), which has no label prop. Worth confirming this is a
deliberate design choice rather than a component that was simply never
wired up — see §7.

## 2. The Universe

`FULL_UNIVERSE` (`engine/us_investing/universe.py`) is a static,
hand-maintained dict of 31 symbols — a mix of `type: "stock"` and
`type: "etf"` entries, each with `name` and `sector`. Same tradeoff as
REIT/InvIT's static universe (`REIT_INVIT_SCORING.md` §2): no
API-discovery risk, but a newly-relevant symbol won't appear until the
file is edited.

`search_us_universe(query)` does a case-insensitive substring match against
symbol/name for this static list only — no price fetch, no live data — used
by the frontend's search-as-you-type.

## 3. Raw Metrics (`_compute_raw_metrics`)

For each symbol, using OHLCV + `info` fetched via `us_investing.service`
(a thin wrapper the underlying data provider sits behind):

- **Price** (USD) and **Price (INR)** — `price × usd_inr_rate` when
  `include_inr=True` (default). The USD/INR rate itself comes from
  `service.get_usd_inr_rate()`.
- **Returns (1m/3m/6m/1y)** — simple period return over 21/63/126/252
  trading days, same formula and same "not a CAGR" caveat as REIT/InvIT's
  returns (`REIT_INVIT_SCORING.md` §3) — 1y and 6m aren't on an
  annualized-comparable basis.
- **Volatility (30d, annualized)** — same formula as REIT/InvIT. Flags
  `high_volatility` above 50% (REIT/InvIT's threshold is 40% — US equities/
  ETFs get a higher bar before being flagged, consistent with equities
  generally running hotter than income trusts).
- **Max Drawdown (1y)** — same formula as REIT/InvIT. Flags `high_drawdown`
  below −35% (REIT/InvIT: −30%).
- **From `info`**: dividend yield, trailing/forward P/E, P/B, beta, average
  volume, market cap, expense ratio + AUM (ETFs), revenue/earnings YoY
  growth. All straight passthroughs from whatever the data provider's
  `info` dict returns — no independent computation or cross-check the way
  REIT/InvIT's yield is derived from actual payout history
  (`REIT_INVIT_SCORING.md` §3) rather than trusted from `info` directly.
- **Risk flags**: `high_pe` (P/E > 60), `low_liquidity` (avg volume <
  100,000), `high_beta` (beta > 2.0) — all threshold checks with no
  category-awareness (a P/E of 65 gets flagged the same whether it's a
  mature utility or a high-growth software company, and ETFs generally
  don't carry a meaningful P/E at all — see §7).
- **Staleness** — same 3-day rule as REIT/InvIT.

Not computed anywhere in this pipeline: analyst targets/ratings,
earnings-surprise history, or any options/short-interest data.

## 4. Conviction Score (`_score_universe`)

Six weighted dimensions, each a **percentile rank against peers**
(`_pct_rank(value, peers, higher_is_better=True)`, identical semantics to
REIT/InvIT's — see `REIT_INVIT_SCORING.md` §4, including the single-peer
degenerate case in §7 below):

| Dimension | Weight | Basis |
|---|---|---|
| return_score | 25% | Blend: 1m × 30% + 1y × 70%, percentile-ranked |
| momentum_score | 20% | 3m return, percentile-ranked |
| downside_protection | 20% | Max drawdown (1y), percentile-ranked **without inversion** — see the note below, this used to be backwards |
| volatility_score | 15% | 30d annualized volatility, `higher_is_better=False` — lower vol ranks higher |
| valuation | 10% | P/E, `higher_is_better=False`, ranked against **same-sector peers** when there are enough of them (see below) |
| liquidity | 10% | Average volume, percentile-ranked |

```python
conviction = clamp(sum(breakdown[k] * weight[k] for k in WEIGHTS), 0, 100)
```

**`downside_protection`'s sign was inverted — fixed (2026-08-23).**
`max_drawdown_1y` is stored as a negative number, where a *shallower* loss
is the numerically *larger* value (`-2 > -15`) — i.e. it's already a
"higher raw value is better" metric, unlike volatility (always positive,
where lower really is the lower raw number). The old code did
`100 - _pct_rank(max_drawdown_1y, peers)`, which double-flipped drawdown's
already-correct ranking: **the fund with the shallower, better drawdown
scored *worse* downside protection than one with a deep loss.** Identical
bug and identical fix to REIT/InvIT's — see `REIT_INVIT_SCORING.md` §4/§8
for the full writeup and a worked example. `_pct_rank` now takes an
explicit `higher_is_better` flag instead of relying on callers to
correctly guess when a manual `100 - rank` is needed.

**Valuation is now sector-relative — fixed (2026-08-23).** The module
docstring always said "P/E vs sector median"; the code didn't do that — it
pooled every instrument's P/E together regardless of sector, so a
richly-valued tech stock and a deep-value energy stock were ranked on the
same scale as if their sectors' normal valuation ranges were equal. Now
`_score_universe` groups P/E by `sector` first and ranks each instrument
against its own sector's pool — but only when that sector has at least
`_MIN_SECTOR_PEERS_FOR_VALUATION` (3) other same-sector instruments with a
valid P/E in the current response; below that, it falls back to the whole
universe's P/E pool for that instrument specifically, since a 1- or
2-name "sector" comparison is as much of a degenerate rank as the
single-instrument bug in §7. With only 31 symbols across many sectors,
expect this fallback to trigger often — it's a real improvement over
always-pooled, not a guarantee of a deep same-sector comparison every time.

**ETFs get a neutral valuation score.** `bd["valuation"] = 50.0` whenever
`pe_ratio` is falsy (`None` or ≤0) — true for essentially all ETFs, which
don't carry a standard trailing P/E the way a single company does. This is
reasonable (an ETF genuinely has no comparable P/E to rank), but it means
`valuation`'s 10% weight is real differentiation for stocks and a flat
tie-breaker-only contribution for every ETF in the universe.

## 5. Confidence & Staleness

**`confidence_score`** — `(filled fields / 5) × 100`, where the 5 fields
are `returns_1y`, `returns_1m`, `volatility_30d`, `max_drawdown_1y`,
`returns_3m`. Notably narrower than REIT/InvIT's 7-field confidence basis
(`REIT_INVIT_SCORING.md` §5) — this module doesn't count `yield_pct` or any
`info`-sourced field (P/E, beta, volume) toward confidence at all, so an
instrument with complete price-history data but entirely missing
fundamentals (e.g. a data-provider gap on `info`) still reports 100%
confidence.

**Stale-data penalty** — identical to REIT/InvIT: `data_quality == "stale"`
→ `confidence -= 30` (floored 0), `conviction *= 0.85`.

## 6. Caching

**Three tiers, same shape as REIT/InvIT's** (`engine/routers/us_investing.py`,
`_get_or_fetch_frame`): in-process dict (`_cached_frame`, 4h TTL) → DB cache
(`utils.db.fetch_us_cache`/`upsert_us_cache`, `us_investing_cache` table) →
live fetch. **Fixed (2026-08-23)**: this used to be in-process only, with
`upsert_us_cache` a literal no-op placeholder — every process restart or
redeploy meant the next request paid the full live-fetch cost across all
31 symbols with nothing served in the meantime, the same starting bug
REIT/InvIT's cache had before it was fixed (`REIT_INVIT_SCORING.md` §6's
history). The DB tier is only used when it has at least as many rows as
`FULL_UNIVERSE` (a partial cache is treated as stale, matching REIT/InvIT's
convention).

**Degraded-frame protection added too** — a fetch where more than 30% of
the returned records have no price (`_is_degraded_frame`) still answers
the request that triggered it but is not written to the DB cache, so a
provider outage can't overwrite a still-good previous snapshot with blanks
for the full TTL. Simpler than REIT/InvIT's version (no separate
short-cooldown in-process TTL for a degraded frame, no risk-flag-based
detection — just the price-null ratio) since US Investing's fetch path
(`us_investing.service.fetch_single`, `ThreadPoolExecutor(8)`) doesn't have
REIT/InvIT's documented per-symbol nested-executor thread-growth risk that
motivated that extra layer there.

**Manual refresh** — `POST /api/us-investing/refresh` now re-reads the
freshly-written DB cache after `run_us_refresh_job()` instead of calling
`build_us_frame()` a second time, matching REIT/InvIT's refresh flow.
**Fixed (2026-08-23)**: this used to fetch live twice per manual refresh
(once inside the job, once to repopulate `_cached_frame`), doubling the
provider load and the wait for every refresh.

Declared routes (`list_us_instruments`, `get_us_detail`) are now plain
`def`, not `async def` — an `async def` route with no real `await` inside
runs directly on uvicorn's single event loop and freezes request handling
for the *entire app* for the duration of a live fetch, the same bug
pattern already fixed for the stock scanner, sector pulse, MF analysis,
and REIT/InvIT routes (this module was missed at the time; **fixed
2026-08-23**).

## 7. Known Gaps & Open Questions

**Fixed (2026-08-23)** — four items previously listed here are resolved;
kept as a record of what changed:

- ~~Single-instrument detail always scores 100 on every dimension~~ — same
  bug and same router-level fix as REIT/InvIT's — see
  `REIT_INVIT_SCORING.md` §8.
- ~~`valuation`'s docstring doesn't match its implementation~~ — the code
  now actually does sector-relative P/E ranking, with a whole-universe
  fallback for thin sectors (§4).
- ~~No DB-backed cache~~ / ~~no degraded-frame protection~~ — both added
  (§6).
- ~~`downside_protection` was inverted~~ — fixed (§4), same bug and fix as
  REIT/InvIT.

**Still open:**

- **No conviction label** — confirm whether this is intentional (§1) or a
  gap versus MF Lab/REIT-InvIT's shared label vocabulary.
- **Risk flag thresholds aren't sector/type-aware** (§3) — a P/E-based flag
  applied uniformly across a 31-symbol mixed stock/ETF universe with no
  per-sector or per-instrument-type baseline. (Note: this is about the
  `high_pe` *risk flag* specifically — the `valuation` *score* is now
  sector-relative per §4; the flag wasn't part of that fix.)
- **11×/31× universe sizes mean coarse percentile ranks**, same caveat as
  REIT/InvIT (`REIT_INVIT_SCORING.md` §4) — more so now that `valuation`
  ranks within (often thin) same-sector groups rather than the whole pool.
- **No absolute/benchmarked equivalent of MF's v1 score** — same as
  REIT/InvIT, every dimension here is peer-relative only.

## 8. What the UI Actually Shows

The US Investing page (`frontend/src/app/us-investing/page.tsx`):

- **Filters** — asset type (stock/ETF), sector (substring match), sort by
  any scored field.
- **`ConvictionScoreCard`** — the same shared component MF Lab and
  REIT/InvIT use, driven by `conviction_score`, `confidence_score`,
  `score_breakdown`. No label badge (§1).
- **Summary stats** — "High Conviction (≥60)" uses a different threshold
  than MF Lab's "High Conviction (≥65)" stat (`MF_SCORING.md` §9) — both
  are UI-only constants, not derived from any shared config, so they can
  (and currently do) diverge without either page knowing about the other's
  threshold.
- **`DataFreshnessBadge`** — reads `last_updated`, stamped as "now" at
  fetch time in `_compute_raw_metrics` (same as REIT/InvIT — a real
  timestamp, not subject to MF Lab's pre-fix date-only parsing issue, see
  `MF_SCORING.md` §9).
