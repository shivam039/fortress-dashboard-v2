# Fortress MF Lab — Conviction Score & Classification Documentation

This documents how a mutual fund's conviction score is actually computed today, how
funds are categorized, and how the "run the scan once a month" caching works. It
follows the same intent as `SCORING.md` (the stock scanner's equivalent document):
an accurate technical reference for review, not marketing copy — including the
places the current implementation falls short of what it appears to do.

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Two Conviction Scores — Read This First](#2-two-conviction-scores--read-this-first)
3. [Fund Discovery & Category Classification](#3-fund-discovery--category-classification)
4. [Raw Metrics (`_score_fund_fast`)](#4-raw-metrics-_score_fund_fast)
5. [Conviction Score v1 (`conviction_engine.score_mf_fund`)](#5-conviction-score-v1-conviction_enginescore_mf_fund)
6. [Conviction Score v2 (`compute_mf_conviction`)](#6-conviction-score-v2-compute_mf_conviction)
7. [Known Gap: Momentum & Efficiency Are Always Neutral](#7-known-gap-momentum--efficiency-are-always-neutral)
8. [Monthly Scan Caching](#8-monthly-scan-caching)
9. [What the UI Actually Shows](#9-what-the-ui-actually-shows)
10. [Open Questions For Review](#10-open-questions-for-review)

---

## 1. Architecture Overview

```
discover_all_funds()              ── mfapi.in /mf, filtered to Direct+Growth
        │                            equity/debt keyword matches
        ▼
fetch_nav_history() / _bulk_preseed_nav_cache()
        │                            NAV history per scheme, DB-cached (20h TTL)
        ▼
_score_fund_fast()                ── raw metrics per fund (returns, vol,
        │                            Sharpe/Sortino, Alpha/Beta, Category)
        ▼
conviction_engine.score_mf_fund() ── CONVICTION SCORE v1 (absolute,
        │                            category-benchmarked) — sorts run_full_mf_scan()'s
        │                            output and is what gets persisted
        ▼
upsert_mf_scan_results()          ── persisted to mf_scan_results (monthly cache)
        │
        ▼
GET /api/mf-analysis              ── serves from the monthly cache if fresh,
        │                            else re-runs the pipeline above
        ▼
enrich_mf_records_with_conviction() ── CONVICTION SCORE v2 (relative,
        │                              peer-percentile-ranked) — computed fresh
        │                              on every request, on top of whatever
        │                              records came back (cached or fresh)
        ▼
Frontend (mf-lab page)            ── displays v2 everywhere (cards, stats,
                                      table's "Conviction Score" column)
```

The important thing this diagram makes explicit: **there are two independently
computed conviction scores**, not one. See §2.

## 2. Two Conviction Scores — Read This First

| | v1 — `Conviction Score` | v2 — `conviction_score_v2` |
|---|---|---|
| Defined in | `utils/conviction_engine.py::score_mf_fund()` | `mf_lab/logic.py::compute_mf_conviction()` |
| Applied by | `enrich_mf_dataframe()`, called inside `run_full_mf_scan()` | `enrich_mf_records_with_conviction()`, called in the `/api/mf-analysis` route handler |
| Methodology | **Absolute**: each sub-score compared against a fixed category benchmark (e.g. "Equity Sharpe should be ≥0.8") | **Relative**: each sub-score is a percentile rank against the *other funds in the same response* |
| Sub-scores | Alpha Quality, Risk-Adjusted Return, Multi-Horizon Return, Downside Protection (4, each 0–25) | performance_consistency, alpha, downside_protection, volatility, momentum, efficiency (6, weighted 0–100) |
| Used for | Sort order of `run_full_mf_scan()`'s output; what gets persisted to `mf_scan_results` | Everything the frontend actually renders: `ConvictionScoreCard`, the stats row (Avg/High Conviction), the table's "Conviction Score" column |
| Extras | `Conviction Label`, `Conviction Emoji`, `Decision` (plain-English) | `confidence_score`, `score_breakdown`, `risk_flags_v2`, `data_quality` |

**These are not the same number and can disagree** — v1 asks "is this fund good in
absolute terms for its category," v2 asks "is this fund good relative to whatever
else is in this particular scan." A fund can rank highly on v1 (beats its category's
fixed Sharpe/return bar) while scoring modestly on v2 (merely average among an
unusually strong peer set that day), or vice versa.

Right now the UI only surfaces v2. v1 still exists, still runs, still determines
persistence order, and is still present in every API response as `Conviction Score`
— it's just not what a user looking at the page is actually seeing. This isn't
flagged anywhere in the UI. See §10 for the case for consolidating these.

## 3. Fund Discovery & Category Classification

`discover_all_funds()` (`mf_lab/logic.py`) hits `GET https://api.mfapi.in/mf`, which
returns essentially every mutual fund scheme in India (tens of thousands of rows,
across every plan/option combination). It's filtered down to:

- name contains **both** "direct" and "growth"
- name contains at least one of the category keywords below
- name does **not** contain "regular" or "idcw"
- if name contains "etf", it must also match a debt keyword (excludes most
  equity ETFs, which aren't actively-managed funds in the sense this scanner
  is built for)

That filtered set (typically low hundreds to low thousands of schemes) is the
"universe" — there is no further curation (no AUM floor, no minimum track record,
no exclusion of near-duplicate share classes beyond the direct/growth filter).

`classify_category(name)` then keyword-matches the scheme name into a primary
**Category** and a granular **Sub Category**. Before matching, hyphens in the
name are normalized to spaces ("Multi-Asset" → "multi asset", "Flexi-Cap" →
"flexi cap") so keywords match both the spaced and hyphenated forms AMCs use
interchangeably:

| Category | Sub Category | Matched on (case-insensitive substrings) |
|---|---|---|
| Debt | Liquid | "liquid" |
| Debt | Money Market | "money market" |
| Debt | Overnight | "overnight", "1 d" |
| Debt | Gilt | "gilt" |
| Debt | Credit Risk | "credit risk" |
| Debt | Duration/Short Term | "duration", "short term", "ultra short" |
| Debt | Corporate/Dynamic Bond | "bond", "debt", "income" |
| Debt | General Debt | (Debt fallback) |
| Equity | ELSS (Tax Saver) | "elss", "tax saver" |
| Equity | Small Cap | "small cap", "smallcap" |
| Equity | Mid Cap | "mid cap", "midcap" |
| Equity | Large Cap | "large cap", "largecap", "bluechip", "top 100" |
| Equity | Flexi Cap | "flexi cap", "flexicap", "flexi" |
| Equity | Multi Cap | "multi cap", "multicap" |
| Equity | Focused | "focused" |
| Equity | Value/Contra | "value", "contra" |
| Equity | Dividend Yield | "dividend yield" |
| Equity | Index Fund | "index", "nifty" |
| Equity | Sectoral/General Equity | (Equity fallback) |
| Hybrid | Arbitrage | "arbitrage" |
| Hybrid | Equity Savings | "equity savings" |
| Hybrid | Balanced Advantage | "balanced advantage", "dynamic asset", "baa" |
| Hybrid | Balanced Hybrid | "balanced hybrid" |
| Hybrid | Conservative Hybrid | "conservative hybrid", "debt hybrid", "conservative" |
| Hybrid | Multi Asset | "multi asset" |
| Hybrid | Aggressive Hybrid | "aggressive hybrid", "equity hybrid", "equity & debt", "equity and debt", "balanced" (generic) |
| Hybrid | General Hybrid | (Hybrid fallback) |

Flexi Cap (min. 65% equity, no cap-size mandate) and Multi Cap (min. 25% each
across large/mid/small cap) used to be merged into one "Flexi/Multi Cap"
bucket even though SEBI treats them as distinct categories with different
mandates — they're now split. Similarly, the Hybrid sub-categories used to
only recognize a scheme name that spelled out "aggressive hybrid" or
"conservative hybrid" verbatim; most real AMC scheme names don't ("Equity &
Debt Fund", "Balanced Fund", "Multi-Asset Allocation Fund"), so in practice
almost every Hybrid fund fell into the catch-all "General Hybrid" bucket.
The keyword list above was broadened to cover those real-world naming
patterns, and "Balanced Hybrid" and "Equity Savings" were added as their own
SEBI-defined categories that were previously missing entirely.

The **primary Category** is decided by checking Hybrid keywords first, then
Debt keywords, and only if neither matches does it fall through to Equity.
Hybrid is checked first specifically because names like "XYZ Debt Hybrid
Fund" or "XYZ Conservative Hybrid Fund" contain a Debt keyword ("debt") as
well as a Hybrid one — checking Debt first would misclassify them as Debt
before their unambiguous "hybrid" signal was ever considered. (An earlier
version of this scanner did check Debt first and documented that as
intentional; it wasn't — it was silently swallowing "Debt Hybrid"-named
funds into the wrong category, which is why Hybrid is now checked first. No
real debt-only or equity-only fund name contains "hybrid", "balanced",
"arbitrage", "advantage", "asset allocation", or "equity savings", so this
reordering can't cause a false positive the other way.)

This is name-based pattern matching against whatever mfapi.in calls the scheme —
there's no cross-check against an authoritative AMFI/SEBI category taxonomy, so a
scheme with an unconventional name can still be misclassified or fall into a
generic "General"/"Sectoral" bucket.

## 4. Raw Metrics (`_score_fund_fast`)

For each fund, using its cached/fetched NAV history:

- **NAV** — latest NAV value.
- **1Y / 3Y / 5Y Return** — CAGR over the trailing N trading days (252/756/1260),
  `None` if the fund has less than ~252 days of history.
- **Volatility** — annualized std dev of daily returns (`std * √252 * 100`).
- **Downside Deviation** — same, but only over negative-return days.
- **Sharpe** — `(annualized mean return − 6% rf) / annualized volatility`.
- **Sortino** — same numerator, denominator is downside deviation instead.
- **Rolling Std** — mean of a 21-day rolling std dev, annualized.
- **Alpha / Beta** — OLS-style covariance/variance of fund vs. benchmark daily
  returns, alpha annualized against a 6% risk-free rate (CAPM-style: `α = (Rp −
  rf) − β(Rm − rf)`).
- **Benchmark** — Nifty 50 by default; Nifty Smallcap 250 or Nifty Midcap 150 if
  the scheme name contains "small cap"/"smallcap" or "mid cap"/"midcap"
  respectively. This benchmark selection is name-keyword-based, same caveat as
  category classification.

Not computed anywhere in this pipeline: expense ratio, 3-month return, AUM, fund
manager tenure, portfolio turnover, or any holdings-level data. See §7.

## 5. Conviction Score v1 (`conviction_engine.score_mf_fund`)

Four sub-scores, each clamped to 0–25, summed to 0–100:

**Alpha Quality (0–25)** — rewards positive alpha up to a cap, penalizes negative
alpha more steeply than it rewards positive:
```
alpha ≥ 0:  25 + min(alpha × 2.0, 15)
alpha < 0:  25 + max(alpha × 3.0, -25)
```

**Risk-Adjusted Return (0–15 Sharpe + 0–10 Sortino = 0–25)** — scaled against a
category-specific Sharpe benchmark:
```
Sharpe benchmark:  Equity 0.8, Hybrid 0.6, Debt 0.5
sharpe_pts  = clamp((Sharpe / benchmark) × 15, 0, 15)
sortino_pts = clamp((Sortino / (benchmark × 1.3)) × 10, 0, 10)
```

**Multi-Horizon Return (0–25)** — 1Y/3Y/5Y return each scaled against a
category return benchmark (Equity 12%, Hybrid 9%, Debt 6% annualized), weighted
10/8/7 points respectively, with a 5-point penalty if 1Y return is more than
2.5× the 3Y annualized return (a "hot fund" front-loading check — flags funds
riding a recent spike rather than showing sustained performance).

**Downside Protection (0–25)** — lower volatility and downside deviation score
higher, benchmarked against a category volatility baseline (Equity 20%, Hybrid
14%, Debt 6%):
```
vol_pts  = clamp(15 - max(0, (Volatility - baseline) × 0.4), 0, 15)
down_pts = clamp(10 - max(0, (Downside Dev - baseline×0.6) × 0.5), 0, 10)
```

Total is clamped to 0–100 and mapped to a label: **STRONG BUY** (≥80), **BUY**
(≥65), **HOLD** (≥50), **UNDERPERFORMER** (≥35), **AVOID** (below 35). A
plain-English `Decision` string is assembled from whichever conditions the fund
actually triggered (notable alpha, strong risk-adjusted returns, high downside
risk, etc).

`run_full_mf_scan()` sorts its output by this score and this is the score that
gets persisted to `mf_scan_results`.

## 6. Conviction Score v2 (`compute_mf_conviction`)

Computed per-request (not persisted) over whatever fund list is currently in
scope — i.e. "peers" means the funds in *this response*, not the whole universe.
Six weighted dimensions:

| Dimension | Weight | Basis |
|---|---|---|
| performance_consistency | 20% | Sharpe + Sortino, percentile-ranked vs peers |
| alpha | 20% | Alpha, percentile-ranked vs peers |
| downside_protection | 20% | Downside Deviation (inverted) + Sortino, percentile-ranked |
| volatility | 15% | Volatility, percentile-ranked (lower = better) |
| momentum | 15% | 3-month return, percentile-ranked — **see §7, this is never populated** |
| efficiency | 10% | Expense ratio, percentile-ranked (lower = better) — **see §7, this is never populated** |

Percentile rank (`_pct_rank_mf`) is `(count of peers ≤ this fund's value) /
peer count × 100`, inverted for "lower is better" metrics. **With fewer than 2
peers with a value, every rank defaults to 50** — so a scan filtered down to a
single fund, or a fund whose comparison metric no peer has, gets a flat neutral
score on that dimension rather than a divide-by-zero or a crash.

The weighted sum becomes `conviction_score`, clamped 0–100. Alongside it:

- **`confidence_score`** — `(filled key fields / 5) × 100` where the 5 key
  fields are Sharpe, Sortino, Alpha, Volatility, Downside Deviation. Reduced
  further (−30, floored at 10) if `NAV Points` indicates under ~90 days of
  history — **this check never fires; see §7**.
- **`risk_flags_v2`** — a list of string flags: `missing_sharpe`,
  `missing_alpha`, `missing_volatility`, `negative_alpha` (alpha < −3%),
  `high_volatility` (>30%), `high_expense_ratio` (>2%, **never fires, see
  §7**), `insufficient_history` (**never fires, see §7**),
  `single_fund_universe`, `stale_data`, `scoring_error`.
- **`data_quality`** — `"complete"` if no risk flags at all, `"stale"` if
  `stale_data` is among them, else `"partial"`. If stale, `conviction_score`
  is also multiplied by 0.85 and confidence reduced by 20.

## 7. Known Gap: Momentum & Efficiency Are Always Neutral

`compute_mf_conviction` reads `fund_stats.get("3M Return")` /
`fund_stats.get("Expense Ratio")` / `fund_stats.get("NAV Points")` — **none of
these keys are ever set anywhere in the pipeline.** `_score_fund_fast()` (§4)
does not compute a 3-month return, does not fetch expense ratio (mfapi.in's API
doesn't expose it; it isn't fetched from any other source either), and does not
compute a NAV-history-length field under either of those key names.

The practical effect:

- **momentum (15% of v2's weight)** silently defaults to 50 for every fund —
  it contributes no differentiation at all between funds. A fund on a genuine
  recent hot streak and one that's been flat both get the same 15-point
  contribution.
- **efficiency (10% of v2's weight)** — same: always exactly 50, ` high_expense_ratio` never flags regardless of what the fund actually charges.
- **`insufficient_history`** never flags and never discounts confidence, even
  for a fund with barely enough history to pass the 210-row minimum elsewhere
  in the pipeline.

**25% of v2's total weight is permanently inert.** This doesn't make the score
wrong exactly — the weighted sum still normalizes correctly — but it means v2 is
effectively a 4-dimension score (alpha, risk-adjusted consistency, downside
protection, volatility) wearing a 6-dimension label. This is directly analogous
to the stock scanner's "50% of the score can't come from IndMoney" finding in
`SCORING.md` — a real, fixable gap worth calling out rather than papering over.

**To fix**: `_score_fund_fast` would need to compute a 3-month return (same
`pct_change(63)`-style calculation already used for 1Y/3Y/5Y, just over ~63
trading days) — cheap, no new data source needed. Expense ratio has no known
source in this pipeline (not in mfapi.in's scheme response); populating it would
require either scraping AMFI's scheme master data or adding a paid data source,
and until then `efficiency` should probably be either dropped from the weighted
sum (redistributing its 10% to the other dimensions) or explicitly documented in
the UI as "not currently available" rather than silently reported as 50/100
alongside four dimensions that are real.

## 8. Monthly Scan Caching

`run_full_mf_scan()` discovers and scores the *entire* filtered fund universe
(§3) — this is expensive (mfapi.in NAV fetch per fund, even with caching, plus
the scoring computation) and the universe doesn't meaningfully change day to
day. So this is designed as a "run about once a month, serve cached results in
between" pipeline, not a "run on every page load" one:

- **`mf_scan_results`** table: one row per `(scheme_code, scan_date)`, storing
  the full scored record as JSON, `UNIQUE(scheme_code, scan_date)` so a same-day
  re-run upserts rather than duplicating.
- **`fetch_mf_cached_results(max_age_days=31)`** — returns the persisted scan if
  its `scan_date` is within the freshness window, empty otherwise. Each returned
  record is stamped with `last_updated` (the scan date) so the UI can show how
  stale it is.
- **`upsert_mf_scan_results(df)`** — called automatically at the end of
  `run_full_mf_scan()`, so any fresh scan (scheduled or manual) persists itself
  for next time.
- **`GET /api/mf-analysis`** — checks `fetch_mf_cached_results(max_age_days=31)`
  first. If it has data, that's served (with v2 conviction re-computed fresh on
  top of it — cheap, no network). Only if the cache is empty/stale does it fall
  through to a full `run_full_mf_scan()`. A `force_refresh=true` query param
  bypasses the cache unconditionally.
- **Manual refresh**: the "Trigger Job" → "Full Recalculation" flow
  (`POST /mf/trigger-job`, `job_type=full_refresh`) runs `run_full_mf_scan()`
  directly regardless of cache freshness, for an on-demand refresh outside the
  monthly cycle.

**Fixed (2026-08-23): a limited or targeted scan could poison this cache for
everyone.** `run_full_mf_scan(limit=N)` and `mf_lab/jobs.py`'s targeted
"Scheme Codes" job path (`full_refresh`/`update_metrics`/
`recalculate_rankings` with specific codes typed into the Trigger Job UI)
both used to call `upsert_mf_scan_results()` unconditionally on whatever
subset they'd just scored. Since `fetch_mf_cached_results` only checks
"is there *any* non-stale row," a single `?limit=5` request — or a normal
user targeting two or three funds via the documented Scheme Codes field —
silently overwrote the shared monthly cache with just that handful of
funds, and every visitor for up to 31 days saw only those few funds instead
of the real universe. Reproduced live in production before the fix landed.
Now: `run_full_mf_scan()` only persists when `limit is None`, and the
targeted job path (renamed `_compute_targeted_snapshot`) never persists at
all — it only ever returns the snapshot for the job's own "processed" count.

**Still open**: this doesn't cover a genuine full (`limit=None`) scan that
gets *interrupted* partway through — e.g. a Render redeploy mid-run, same
failure shape already fixed for the Bhav Copy backfill (see
`docs/market-data.md`). `upsert_mf_scan_results()` is called once, after
the whole `ThreadPoolExecutor` batch completes, so an interrupted run
should mean the call never happens at all — but if that write itself isn't
one atomic transaction (unverified either way as of this writing), a kill
mid-write could still leave a partial-but-genuinely-full-scan set of rows
stamped with today's date, which `fetch_mf_cached_results` has no way to
distinguish from a deliberately smaller-but-complete universe. Worth
verifying `upsert_mf_scan_results`'s transaction boundaries directly if
this becomes a live-observed problem again.

Nothing currently *schedules* a monthly re-scan automatically (e.g. no cron/
scheduled task calling `full_refresh`) — the 31-day cache means data can go
stale for up to a month if nobody visits the page or manually triggers a
refresh in that window and nothing else prompts a rescan. If an unattended
monthly refresh is wanted, it needs a scheduled trigger calling
`POST /mf/trigger-job` with `job_type=full_refresh`, or an equivalent cron-style
job — this doesn't exist yet.

## 9. What the UI Actually Shows

The MF Lab page (`frontend/src/app/mf-lab/page.tsx`):

- **Category / Sub Category filters** — chip rows above the fund table, driven
  entirely by whatever `Category`/`Sub Category` values are present in the
  current response (§3). Sub Category is scoped to the active Category.
- **Fund Analysis table** — a curated column set (`Scheme`, `Category`, `Sub
  Category`, `Conviction Score`, `Conviction Label`, `Confidence`, `Data
  Quality`, `NAV`, returns, and the raw risk metrics), where the "Conviction
  Score" column is `conviction_score_v2` (§2), not the persisted v1 score.
  **Fixed (2026-08-23)**: "Conviction Label" in this table is no longer the
  raw v1 label passed through from the API — it's now derived in the
  frontend from the *same* v2 score the column displays (🟢 Strong ≥70, 🟡
  Moderate ≥45, 🔴 Weak below, matching `ConvictionScoreCard`'s own
  thresholds). Previously the table showed v2's score next to v1's label —
  e.g. a v2 score of 25.8 next to the label "STRONG BUY" — two individually
  correct but mutually contradictory-looking numbers from unrelated scoring
  systems in the same row. The API response is unchanged (still returns
  both `Conviction Label` (v1) and the v2 fields); only this one frontend
  table's display column was fixed. The underlying "should v1 and v2 be
  consolidated" question in §10 is still open — this only fixed the most
  visibly broken symptom of it.
- **Conviction Grid / Conviction Detail panel** — `ConvictionScoreCard`, driven
  entirely by v2's score, confidence, `score_breakdown`, and `risk_flags_v2`.
- **Stats row** (Funds Analyzed, Avg Conviction, High Conviction ≥65, Stale
  Data) — all computed from v2 fields (`conviction_score_v2`, `data_quality`).
- **Freshness badge** — reads `last_updated` off the first record.
  **Fixed (2026-08-23)**: this used to be `str(scan_date)` — a bare
  `"YYYY-MM-DD"` with no time-of-day or timezone. `new Date("2026-08-23")`
  parses as UTC midnight, so for a viewer east of UTC (e.g. IST, UTC+5:30) a
  scan that had just finished could already read as several hours old, or
  even "1d ago," depending on time of day — reproduced live. `fetch_mf_cached_results`
  now selects the table's actual `updated_at` (a real `timestamptz`) and
  normalizes it to a UTC ISO string instead. On a genuine cache miss (fresh
  scan, no round-tripped `scan_date`/`updated_at` on the in-memory records)
  the badge still won't render — that part is unchanged.

## 10. Open Questions For Review

- **Should v1 and v2 be consolidated into one score?** Having two systems
  computing two different numbers both called "conviction score" (one visible,
  one persisted-but-hidden) is a maintenance and trust hazard — a future change
  to one is easy to make without realizing the other exists. At minimum, the
  API response should probably be relabeled so `Conviction Score` (v1) and
  `conviction_score_v2` aren't both present under confusingly similar names.
  The table's *label* mismatch was patched at the display layer (§9), but the
  API still returns both scores under near-identical names — a consumer of
  the raw API (not the frontend) can still be misled the same way the UI used
  to be. **Partially addressed (2026-08-23)**: `enrich_mf_records_with_conviction`
  now also adds `conviction_score_v1`/`conviction_label_v1`/`conviction_emoji_v1`
  as explicit aliases of the existing `Conviction Score`/`Conviction Label`/
  `Conviction Emoji` fields — purely additive, originals untouched for
  backward compatibility. A new API consumer can now ask for "the v1 score"
  unambiguously without needing to already know that `Conviction Score`
  (spaced, title-cased) means v1. This doesn't consolidate the two scores —
  that question is still open — it just makes both self-describing at the
  API layer, not only in the frontend table.
- **Should momentum/efficiency be fixed or removed from v2's weights?** See §7
  — right now they're silently inert. Either populate real inputs (3M return is
  cheap; expense ratio needs a new data source) or stop weighting them until
  there's real data behind them.
- **Should there be a scheduled monthly refresh?** Right now "once a month" is
  enforced only as a read-side cache TTL, not an active schedule — see §8.
- **No absolute-quality floor on discovery** — `discover_all_funds()` includes
  every direct-growth scheme matching a keyword, regardless of AUM, age, or
  track record. A 3-month-old micro-cap fund with a lucky short run and a
  20-year-old flagship fund are scored on equal footing (both v1's benchmarks
  and v2's peer-percentile ranking treat them the same way).
