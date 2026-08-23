# Fortress REITs & InvITs — Conviction Score Documentation

> **Primary file:** `engine/reit_invits/logic.py`
> **Supporting modules:** `engine/reit_invits/universe.py`, `engine/routers/reit_invits.py`, `engine/reit_invits/jobs.py`, `engine/utils/conviction_engine.py` (shared label vocabulary)

This documents how a REIT/InvIT's conviction score is actually computed today —
an accurate technical reference, following the same intent and style as
`SCORING.md` (stock scanner) and `MF_SCORING.md` (mutual funds): what the code
does, not what it appears to do, including where it falls short.

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [The Universe](#2-the-universe)
3. [Raw Metrics (`_compute_raw_metrics`)](#3-raw-metrics-_compute_raw_metrics)
4. [Conviction Score (`_score_universe`)](#4-conviction-score-_score_universe)
5. [Confidence, Staleness & the Valuation Note](#5-confidence-staleness--the-valuation-note)
6. [Caching](#6-caching)
7. [What the UI Actually Shows](#7-what-the-ui-actually-shows)
8. [Known Gaps & Open Questions](#8-known-gaps--open-questions)

---

## 1. Architecture Overview

```
REIT_INVIT_UNIVERSE (static, 11 symbols)
        │
        ▼
_fetch_history()                  ── 1y daily OHLCV via yfinance
_fetch_distribution_history()     ── real per-unit payouts (.dividends), not
        │                            yfinance's often-stale info.dividendYield
        ▼
_compute_raw_metrics()            ── per-symbol: returns, volatility, max
        │                            drawdown, yield, distribution growth,
        │                            NAV premium/discount, risk flags
        ▼
_score_universe()                 ── CONVICTION SCORE (relative,
        │                            peer-percentile-ranked within
        │                            whatever list was just fetched)
        ▼
GET /api/reit-invits              ── serves from a 3-tier cache (§6),
                                      falls back to a live fetch
```

Unlike the stock scanner (one absolute score) or MF Lab (two independently
computed scores, v1 and v2 — see `MF_SCORING.md` §2), REITs & InvITs have
**exactly one** conviction score, and it's peer-relative only — there is no
absolute/category-benchmarked equivalent of MF's v1 score here.

REITs and InvITs are scored by the **same code, same weights, same universe
list** — `asset_class` (`"REIT"` or `"InvIT"`, from `REIT_INVIT_UNIVERSE`'s
static metadata) is just a label on the record, not a branch in the scoring
logic. See §8 for why this is worth questioning.

## 2. The Universe

`REIT_INVIT_UNIVERSE` (`engine/reit_invits/universe.py`) is a static,
hand-maintained dict of 11 NSE-listed symbols — every listed Indian REIT and
InvIT was small enough in 2026 that a curated list was practical, unlike MF
Lab's live `discover_all_funds()` API-driven discovery. Each entry carries
`name`, `type` (REIT/InvIT), `sub_type` (e.g. "Office", "Retail Mall",
"Power Transmission"), `sponsor`, and `sector` (always "Real Estate" today,
even for non-real-estate InvITs like power/road/gas-pipeline trusts — see
§8).

Because discovery is static rather than API-driven, there's no equivalent of
MF Lab's "the universe silently grows/shrinks based on what an external API
returns" risk — but it also means a newly-listed REIT/InvIT won't appear
until someone edits this file.

## 3. Raw Metrics (`_compute_raw_metrics`)

For each symbol, using 1y of daily OHLCV (`_fetch_history`, yfinance,
2 retries, 12s per-call timeout):

- **Price** — latest close.
- **Returns (1m/3m/6m/1y)** — simple `(curr − past) / past × 100` over the
  trailing N trading days (21/63/126/252); `None` if fewer than N+1 days of
  history exist. Unlike the MF/stock pipelines, this is **not** a CAGR —
  it's a raw period return, so 1y and 6m aren't on an annualized-comparable
  basis with each other.
- **Volatility (30d, annualized)** — `daily_returns.tail(30).std() × √252 × 100`.
  Flags `high_volatility` above 40%.
- **Max Drawdown (1y)** — largest peak-to-trough decline over the trailing
  year (`(close − cummax) / cummax`, minimum value). Flags `high_drawdown`
  below −30%.
- **Distribution history** (`_fetch_distribution_history`) — pulled from
  yfinance's `.dividends` corporate-actions feed, which for a REIT/InvIT is
  its actual quarterly (usually) unit-holder payouts:
  - `distributions_1y` / `distributions_3y` — ₹/unit total paid out over the
    trailing 1y/3y.
  - `distribution_count_1y` — how many payouts made up the 1y total (a
    consistency signal — most trusts pay quarterly, so 4 is "normal").
  - `distribution_growth_3y_pct` — trailing-12-months payouts vs. the
    12 months ending ~3 years ago (i.e. is the distribution trending up or
    down over the trust's history, not noisy quarter-to-quarter movement).
    `None` for any trust without 3 years of listed history — most Indian
    REITs/InvITs, since the vehicle type itself is relatively young in
    India (first REIT listed 2019).
- **Yield %** — `distributions_1y / price × 100`, i.e. computed from the
  *real* trailing payout record above, not yfinance's `info.dividendYield`
  field (which is frequently stale, missing, or based on a single most-recent
  payout rather than a trailing-12-month total for this instrument type).
  Only falls back to `info.dividendYield`/`info.yield` when a trust doesn't
  have a full year of listed history yet.
- **NAV premium/discount** — `info.bookValue` is used as a NAV-per-unit
  proxy; `nav_premium_pct = (price − nav) / nav × 100`. See §8 for why
  `bookValue` is an imperfect proxy for REIT/InvIT NAV specifically.
- **Staleness** — if the most recent price bar is more than 3 days old,
  `data_quality = "stale"` and a `stale_data` risk flag is added.

Not computed anywhere in this pipeline: AUM/market cap, occupancy rate,
WALE (weighted average lease expiry), gearing/leverage ratio, or any
portfolio-composition data — all of which are standard REIT/InvIT-specific
quality signals that don't come from a generic yfinance OHLCV+info fetch.

## 4. Conviction Score (`_score_universe`)

Six weighted dimensions, each a **percentile rank against same-type peers**
(`_pct_rank(value, peers, higher_is_better=True)` —
`(peers ≤ this value) / peer count × 100`, or its complement when
`higher_is_better=False`; returns 50 if there are fewer than 2 peer values —
see §8 for why that floor matters):

| Dimension | Weight | Basis |
|---|---|---|
| yield_score | 20% | Trailing 12m distribution yield, percentile-ranked (`higher_is_better=True`) |
| distribution_growth_score | 15% | 3y distribution growth, percentile-ranked (funds without 3y history rank at the neutral 50, not penalized for being newer listings) |
| return_score | 20% | Blend: 1m return × 30% + 1y return × 70%, each percentile-ranked separately then combined |
| downside_protection | 15% | Max drawdown (1y), percentile-ranked **without inversion** — see the note below, this used to be backwards |
| volatility_score | 15% | 30d annualized volatility, percentile-ranked with `higher_is_better=False` — lower vol ranks higher |
| momentum_score | 15% | 3m return, percentile-ranked |

```python
conviction = clamp(sum(breakdown[k] * weight[k] for k in WEIGHTS), 0, 100)
```

**Peer grouping is scoped to `asset_class` (REIT vs. InvIT), not pooled.**
Every dimension above ranks an instrument against same-type peers first
(`_peers_for`), falling back to the whole valid universe only when the
same-type group has fewer than 2 values for that metric — e.g. a data
outage that leaves only one REIT with a usable metric that day. **Fixed
(2026-08-23)**: this used to pool all REITs and InvITs into one peer list
for every dimension — see §8 for why that's a real methodological problem
(the two instrument types have structurally different normal yield/
volatility ranges) and not just a labeling nitpick.

**`downside_protection`'s sign was inverted — fixed (2026-08-23).**
`max_drawdown_1y` is stored as a negative number, where a *shallower* loss
is the numerically *larger* value (`-2 > -15`) — i.e. it's already a
"higher raw value is better" metric, unlike volatility (always positive,
where lower really is the lower raw number). The old code did
`100 - _pct_rank(max_drawdown_1y, peers)` for every "lower is better"
dimension uniformly, which double-flipped drawdown's already-correct
ranking: **the fund with the shallower, better drawdown scored *worse*
downside protection than one with a deep loss.** Verified directly: two
REITs with -5% and -15% drawdowns respectively scored `downside_protection`
= 0 and 50 (backwards) before the fix, 100 and 50 (correct) after. `_pct_rank`
now takes an explicit `higher_is_better` flag (same convention as
`mf_lab.logic._pct_rank_mf`, which already had this and never had the bug)
so the direction is stated at each call site instead of inferred from a
metric-by-metric mental model of which raw values are "low."

The weighted sum is a straight linear blend — no IQR winsorization, no
sector/peer-group z-scoring, no regime multiplier (all present in the stock
scanner's `apply_advanced_scoring`, see `SCORING.md` §4–5). With 5 REITs and
6 InvITs, percentile rank is coarse by construction even within one type —
each additional same-type peer only ever moves your rank by ~17-20
percentage points, so two instruments that are meaningfully different on a
raw metric can still land on the same rounded percentile.

The resulting `conviction_score` is then mapped to a shared label via
`utils.conviction_engine._label()` — the same vocabulary used by the stock
scanner and MF Lab v1: **STRONG BUY** (≥80), **BUY** (≥65), **HOLD** (≥50),
**UNDERPERFORMER** (≥35), **AVOID** (below 35).

## 5. Confidence, Staleness & the Valuation Note

**`confidence_score`** — `(filled fields / 7) × 100`, where the 7 fields are
`yield_pct`, `returns_1y`, `returns_1m`, `volatility_30d`, `max_drawdown_1y`,
`returns_3m`, `distributions_1y`. `distribution_growth_3y_pct` is
**deliberately excluded** from this list — most listed Indian REITs/InvITs
are under 3 years old, so penalizing confidence for a legitimately-absent
3y-growth figure would just be penalizing newness, not real data
incompleteness.

**Stale-data penalty** — if `data_quality == "stale"` (no fresh price bar in
>3 days): `confidence -= 30` (floored at 0) and `conviction *= 0.85`. Applied
*after* the percentile-rank scoring, so a stale instrument's raw sub-scores
are computed exactly like everyone else's and then discounted at the end.

**Valuation note** — a plain-language sentence describing where the unit
trades relative to its NAV proxy (§3), *not* folded into the numeric score:

| NAV premium/discount | Note |
|---|---|
| ≤ −5% | "Trading X% below NAV — potential value entry if fundamentals hold" |
| −5% to +5% | "Trading close to NAV (X%) — fairly valued" |
| +5% to +15% | "Trading X% above NAV — a moderate premium" |
| > +15% | "Trading X% above NAV — a rich premium, limited margin of safety" |

Kept out of the weighted score explicitly because the NAV-proxy data
(`info.bookValue`) is inconsistent across trusts (§8) — treated as
informational context, not a scored input.

## 6. Caching

Three tiers, checked in order (`engine/routers/reit_invits.py`):

1. **In-process dict** (`_cached_frame`) — fastest, doesn't survive a
   process restart. TTL depends on whether the cached frame is "healthy" or
   "degraded" (see below): 4 hours healthy, 3 minutes degraded.
2. **DB cache** (`utils.db.fetch_reit_cache`/`upsert_reit_cache`,
   `reit_cache` table) — survives a restart. Only used if it has at least as
   many rows as the current universe size (a partial DB cache is treated as
   stale, not served).
3. **Live fetch** (`build_reit_frame()`) — a `ThreadPoolExecutor(6)` across
   the 11-symbol universe, each symbol doing up to 3 yfinance calls
   (history + dividends + info), each individually timeout-guarded at 12s,
   with a 45s overall batch timeout (`_BATCH_TIMEOUT_S`) so one stuck symbol
   can't hang the whole request.

**Degraded-frame handling**: if more than 30% of a freshly-fetched frame is
placeholder/error rows (`_is_degraded_frame` — `fetch_timeout`/`fetch_error`
flags, or no price at all), the frame is treated as *degraded*: it's still
served to the request that triggered it and kept in the in-process cache for
3 minutes (so a burst of concurrent requests during an outage doesn't each
trigger their own full live-fetch attempt — each attempt spins up roughly
two dozen short-lived threads across the universe), but it is **not** written
to the DB cache. This specifically protects against overwriting a
still-good previous DB snapshot with blanks during a transient yfinance
outage — a real failure mode this module's comments describe hitting in
production (yfinance is frequently rate-limited from cloud-provider IPs,
Render included).

**Manual refresh** — `POST /api/reit-invits/refresh` runs
`reit_invits.jobs.run_reit_refresh_job()` (live fetch + DB upsert + job
bookkeeping) in the background, then re-reads the freshly-written DB cache
rather than fetching live a second time.

Nothing schedules an automatic periodic refresh — same open question as MF
Lab's monthly scan (`MF_SCORING.md` §8), though the 4-hour TTL here is much
shorter than MF's 31-day one, so staleness caps out lower even with no
active schedule.

## 7. What the UI Actually Shows

The REITs & InvITs page (`frontend/src/app/reit-invits/page.tsx`):

- **Sort dropdown** — Conviction Score, Yield %, Distribution (1Y), 1Y
  Return, 1M Return, Confidence — all direct fields off the scored record,
  sorted client-independent (the API does the sort, per `sort_by`/`desc`
  query params).
- **Signal badge** — the shared label vocabulary (§4), color-coded green
  (STRONG BUY/BUY), amber (HOLD/UNDERPERFORMER), red (AVOID) — same palette
  convention as MF Lab and the stock scanner.
- **`ConvictionScoreCard`** — same shared component MF Lab and US Investing
  use, driven by `conviction_score`, `confidence_score`, `score_breakdown`,
  and `risk_flags`.
- **Valuation note** (§5) — shown as plain text, not scored.
- **`DataFreshnessBadge`** — reads whatever `last_updated` the record
  carries (`_compute_raw_metrics` stamps this as "now" at fetch time, so
  unlike MF Lab's date-only `scan_date` field, this one is already a full
  timestamp and isn't subject to the same UTC-midnight parsing issue MF Lab
  had before its fix — see `MF_SCORING.md` §9).

## 8. Known Gaps & Open Questions

**Fixed (2026-08-23)** — three items previously listed here are resolved;
kept as a record of what changed and why, since the underlying reasoning
(especially on peer-grouping) is still relevant context:

- ~~Single-instrument detail always scores 100 on every dimension~~ — was:
  `reit_invits.logic.get_reit_detail(symbol)` called `_score_universe([raw])`,
  a peer list of exactly one instrument, itself; `_pct_rank(value, [value])`
  is mathematically always `1/1 × 100 = 100`. Fixed at the router level:
  `GET /api/reit-invits/{symbol}` now looks the requested symbol up from
  the same cached, full-universe-scored frame `GET /api/reit-invits`
  serves (`routers/reit_invits.py`), so it's ranked against its real peers.
  `_pct_rank` was also hardened as defense-in-depth (§4: fewer than 2 peers
  → neutral 50) for any future direct caller of the logic-level function,
  which still has the single-peer shape if called on its own.
  **The same bug and the same fix shape applied to US Investing's
  `get_us_detail`** — see `US_INVESTING_SCORING.md` §7.
- ~~REIT and InvIT are scored identically, pooled together~~ — was: all 11
  instruments shared one peer pool per dimension despite REITs (commercial
  real estate, rental-income-driven) and InvITs (regulated infrastructure,
  contracted-cashflow-driven) having structurally different normal yield
  and volatility ranges. Fixed: peer ranking is now scoped to `asset_class`
  (§4), falling back to the whole universe only when a same-type group is
  too thin (fewer than 2 values) to rank against.
- ~~`sector` is always "Real Estate"~~ — this claim in an earlier version
  of this doc was simply wrong; `REIT_INVIT_UNIVERSE` (`reit_invits/
  universe.py`) already sets `sector: "Infrastructure"` for every InvIT
  and `sector: "Real Estate"` only for actual REITs, and `_compute_raw_metrics`'s
  `meta.get("sector", "Real Estate")` fallback (the source of the original,
  incorrect claim here) never actually triggers because every universe
  entry sets `sector` explicitly. Corrected.

**Still open:**

- **NAV proxy (`info.bookValue`) is a stretch for this instrument type.**
  "Book value" in yfinance's `info` dict is a generic equity-accounting
  field; for a trust structure like a REIT/InvIT, actual NAV is normally
  disclosed separately by the trust (asset valuations, less debt, divided
  by units outstanding) and isn't guaranteed to be what yfinance surfaces
  under `bookValue` for these symbols. The valuation note (§5) is
  explicitly informational rather than scored for this reason, but it's
  still shown to users as if it were a reliable NAV comparison — worth
  verifying against a real disclosed-NAV source (e.g. the trust's own
  investor-relations filings) before trusting it for anything beyond a
  rough directional signal.
- **11-symbol universe (5 REITs, 6 InvITs) means coarse percentile ranks**
  (§4), more so now that ranking is type-scoped rather than pooled — worth
  keeping in mind when reading small differences in conviction score as
  meaningful.
- **No absolute/benchmarked equivalent of MF's v1 score** — every dimension
  here is peer-relative only. In a universe where all 11 instruments are
  having a bad year, the "best" one still ranks near 100 on
  `return_score`/`momentum_score`, with nothing in the score itself
  communicating "good compared to peers, but still absolutely weak."
- **No scheduled refresh** — same as MF Lab (§6).
