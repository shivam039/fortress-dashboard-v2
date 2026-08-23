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

Not computed anywhere in this pipeline: sector-relative valuation (P/E vs.
sector median is *documented* in this file's own module docstring as the
`valuation` sub-score's basis — see §4 for why that's not actually what
happens), analyst targets/ratings, earnings-surprise history, or any
options/short-interest data.

## 4. Conviction Score (`_score_universe`)

Six weighted dimensions, each a **percentile rank against the other
instruments in the current response** (`_pct_rank`, identical semantics to
REIT/InvIT's — see `REIT_INVIT_SCORING.md` §4, including the single-peer
degenerate case in §7 below):

| Dimension | Weight | Basis |
|---|---|---|
| return_score | 25% | Blend: 1m × 30% + 1y × 70%, percentile-ranked |
| momentum_score | 20% | 3m return, percentile-ranked |
| downside_protection | 20% | Max drawdown (1y), inverted percentile rank |
| volatility_score | 15% | 30d annualized volatility, inverted percentile rank |
| valuation | 10% | P/E, inverted percentile rank (lower P/E ranks higher) — **within this response's universe, not sector-relative; see below** |
| liquidity | 10% | Average volume, percentile-ranked |

```python
conviction = clamp(sum(breakdown[k] * weight[k] for k in WEIGHTS), 0, 100)
```

**The module docstring says "P/E vs sector median" — the code doesn't do
that.** `_score_universe` builds one flat `pes` list from every instrument
in the response with a positive P/E (stocks and ETFs, every sector,
together) and ranks each instrument against that single combined list —
there is no per-sector grouping or per-sector median anywhere in this
function. A richly-valued tech stock and a deep-value energy stock are
ranked on the same P/E percentile scale as if their sectors' normal
valuation ranges were the same. This is the same shape of
documentation-vs-implementation drift `SCORING.md` and `MF_SCORING.md`
were written to catch elsewhere in this app — flagged here rather than
silently trusting the docstring.

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

**Single tier, in-process only** (`engine/routers/us_investing.py`):
`_cached_frame` + `_cache_ts`, 4-hour TTL, no DB-backed persistence layer.
This is meaningfully simpler than both MF Lab (DB-backed monthly cache,
`MF_SCORING.md` §8) and REIT/InvIT (3-tier: in-process → DB → live,
`REIT_INVIT_SCORING.md` §6) — there is no `us_investing_cache`-equivalent
table, so **every process restart or redeploy means the next request pays
the full live-fetch cost again**, for all 31 symbols, with nothing served
in the meantime. For a 31-symbol universe this is a smaller blast radius
than MF Lab's hundreds-to-thousands-fund universe was before its DB cache
existed, but it's the same shape of gap MF Lab had (`MF_SCORING.md` §8's
history) — worth deciding whether US Investing needs the same fix, or
whether the smaller universe genuinely makes it a non-issue in practice.

There's also no degraded-frame protection here (contrast REIT/InvIT §6's
`_is_degraded_frame` handling) — a provider outage that returns mostly
empty/error records for this batch gets cached and served as-is for the
full 4 hours, with no distinction from a healthy fetch.

**Manual refresh** — `POST /api/us-investing/refresh` runs
`us_investing.jobs.run_us_refresh_job()` in the background, then calls
`build_us_frame()` again to repopulate the in-process cache — i.e. it
fetches live twice per manual refresh (once inside the job, once to
refresh `_cached_frame`), unlike REIT/InvIT's refresh flow which explicitly
re-reads the job's own DB write instead of double-fetching
(`REIT_INVIT_SCORING.md` §6).

## 7. Known Gaps & Open Questions

- **Single-instrument detail always scores 100 on every dimension —
  identical bug to REIT/InvIT.** `get_us_detail(symbol)` calls
  `_score_universe([raw])`, a peer list of exactly one instrument (itself).
  `_pct_rank(value, [value])` = 100 unconditionally for every dimension.
  `GET /api/us-investing/{symbol}` therefore returns a conviction score
  that's mathematically guaranteed to be 100 (before the confidence/
  staleness discount) regardless of the instrument's actual metrics. See
  `REIT_INVIT_SCORING.md` §8 for the matching writeup and the shared fix
  direction (rank against the full universe's peer values, not a
  single-element list containing only the instrument being scored).
- **`valuation`'s docstring ("P/E vs sector median") doesn't match its
  implementation** (§4) — either fix the code to actually group by sector,
  or fix the docstring/comment to describe what it really does
  (universe-wide P/E percentile).
- **No conviction label** — confirm whether this is intentional (§1) or a
  gap versus MF Lab/REIT-InvIT's shared label vocabulary.
- **No DB-backed cache** (§6) — every restart pays a full live-fetch, with
  no degraded-frame protection during a provider outage.
- **Risk flag thresholds aren't sector/type-aware** (§3) — a P/E-based flag
  applied uniformly across a 31-symbol mixed stock/ETF universe with no
  per-sector or per-instrument-type baseline.
- **11×/31× universe sizes mean coarse percentile ranks**, same caveat as
  REIT/InvIT (`REIT_INVIT_SCORING.md` §4).
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
