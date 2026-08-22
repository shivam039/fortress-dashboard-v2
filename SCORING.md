# Fortress Conviction Engine — Scoring Documentation

> **Last updated:** July 2026  
> **Primary file:** `engine/stock_scanner/logic.py`  
> **Supporting modules:** `engine/stock_scanner/pulse.py`, `engine/stock_scanner/config.py`, `engine/fortress_config.py`

---

## Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1 — Raw Conviction (Per-Stock)](#2-phase-1--raw-conviction-per-stock)
   - [2.1 Data Inputs](#21-data-inputs)
   - [2.2 Trend Structure (Technical Foundation)](#22-trend-structure-technical-foundation)
   - [2.3 ADX — Trend Strength](#23-adx--trend-strength)
   - [2.4 52-Week High Distance](#24-52-week-high-distance)
   - [2.5 Relative Strength vs Nifty 50](#25-relative-strength-vs-nifty-50)
   - [2.6 Volume & Breakout Confirmation](#26-volume--breakout-confirmation)
   - [2.7 Volatility Contraction (VCP)](#27-volatility-contraction-vcp)
   - [2.8 Over-Extension Guard](#28-over-extension-guard)
   - [2.9 Analyst Dispersion](#29-analyst-dispersion)
   - [2.10 War/News Resilience & Gap Integrity](#210-warnews-resilience--gap-integrity)
   - [2.11 News Sentiment & Black Swan Detection](#211-news-sentiment--black-swan-detection)
   - [2.12 Earnings Calendar Risk](#212-earnings-calendar-risk)
3. [Phase 2 — Sub-Score Computation (Raw Components)](#3-phase-2--sub-score-computation-raw-components)
   - [3.1 Technical Raw](#31-technical-raw)
   - [3.2 Fundamental Raw](#32-fundamental-raw)
   - [3.3 Sentiment Raw](#33-sentiment-raw)
   - [3.4 Context Raw](#34-context-raw)
4. [Phase 3 — Universe-Relative Normalization (`apply_advanced_scoring`)](#4-phase-3--universe-relative-normalization-apply_advanced_scoring)
   - [4.1 Sector Z-Score Adjustment](#41-sector-z-score-adjustment)
   - [4.2 IQR Normalization](#42-iqr-normalization)
   - [4.3 RS Rank Bonus](#43-rs-rank-bonus)
   - [4.4 Sector Rotation Bonus](#44-sector-rotation-bonus)
   - [4.5 Weighted Score Composition](#45-weighted-score-composition)
5. [Phase 4 — Regime Multiplier](#5-phase-4--regime-multiplier)
   - [5.1 Regime Detection Logic (`pulse.py`)](#51-regime-detection-logic-pulsepy)
   - [5.2 5-Tier Regime Table](#52-5-tier-regime-table)
6. [Phase 5 — Quality Gates](#6-phase-5--quality-gates)
7. [Final Verdict Logic](#7-final-verdict-logic)
8. [Weight Configuration](#8-weight-configuration)
9. [Scoring Flow Diagram](#9-scoring-flow-diagram)
10. [Design Decisions & Rationale](#10-design-decisions--rationale)

---

## 1. Architecture Overview

The conviction score is computed in **five sequential phases**, each adding a different layer of intelligence:

```
Phase 1: Raw Conviction        → Integer score 0–100 per stock (per-stock technical/news signals + explicit risk penalties)
Phase 2: Sub-Score Components  → technical_raw, fundamental_raw, sentiment_raw, context_raw
Phase 3: Normalization         → Universe-relative percentile scoring via IQR normalization
Phase 4: Regime Multiplier     → Market context adjustment (Bull/Bear/Range etc.)
Phase 5: Quality Gates         → Hard disqualification filters (liquidity, price, leverage)
─────────────────────────────────────────────────────────────────────────
Final Score: 0–100 (displayed as "Conviction")
Verdict:     🔥 HIGH / 🚀 PASS / 🟡 WATCH / ❌ FAIL / 🚨 AVOID
```

**Why two scoring paths (conviction + sub-scores)?**  
`check_institutional_fortress()` computes *absolute* conviction points per stock in isolation, including explicit negative penalties for risk events. `apply_advanced_scoring()` computes *relative* scores comparing stocks within the scanned universe. The final `Score` shown in the UI is the universe-relative score after regime adjustment, while the raw per-stock conviction remains available for audit and debugging.

---

## 2. Phase 1 — Raw Conviction (Per-Stock)

**Function:** `check_institutional_fortress(ticker, data, ...)`  
**Returns:** Dict with `Score` (= raw `conviction`, capped 0–100)  
**Starts at:** `conviction = 0`

---

### 2.1 Data Inputs

| Input | Source | Notes |
|---|---|---|
| OHLCV (1y daily) | **INDstocks/INDmoney** via `get_stock_data()`, yfinance fallback | Minimum 210 trading days required. INDstocks is tried first (single-symbol and, since the batch-OHLCV fix, whole-universe scans too); a scan only uses INDstocks data if it covers *every* ticker in the batch, otherwise the whole scan falls back to yfinance — never mixes providers mid-scan. See `docs/market-data.md`. |
| Ticker metadata | `yfinance.Ticker.info` | Analyst targets, market cap, D/E, interest coverage. **No INDstocks equivalent** — INDstocks' documented endpoints cover quotes/historical/instruments/option-chains only, not company fundamentals, so this stays yfinance-only regardless of the OHLCV provider. |
| News | `yfinance.Ticker.news` | Last 10 items, used only for Black Swan detection. Same as above — yfinance-only, no INDstocks equivalent. |
| Earnings dates | `yfinance.Ticker.earnings_dates` | Last reported quarter surprise %. yfinance-only. |
| Earnings calendar | `yfinance.Ticker.calendar` | Upcoming earnings date for event risk. yfinance-only. |
| Nifty 50 benchmark | `yfinance "^NSEI"` | Used for RS computation. Still yfinance even when OHLCV for the stock itself comes from INDstocks — the instruments cache `get_stock_data`'s INDstocks path uses only covers `source=equity`, not indices, so `^NSEI` never resolves to an INDstocks scrip code today. |

**Weight-vs-source reality check:** `DEFAULT_SCORING_CONFIG` weights Technical 50% / Fundamental 25% / Sentiment 15% / Context 10%. Only the Technical score's price/volume inputs can come from INDstocks; Fundamental + Sentiment + Context (50% of the total weight) are yfinance-sourced unconditionally, by API availability, not by choice — there's currently nowhere else to get that data from. Moving OHLCV to INDstocks does not and cannot make the other half of the score "IndMoney-sourced" too.

All metadata is fetched via `_ensure_metadata_loaded()` and cached in module-level dicts (`_INFO_CACHE`, `_NEWS_CACHE`, `_CAL_CACHE`, `_EARN_CACHE`) for the life of the process, and persisted to the `ticker_metadata` DB table (`upsert_ticker_metadata_cache`) so later scans can skip live yfinance calls for tickers with a recent-enough entry. `stock_scanner.logic.prefetch_metadata(tickers)` bulk-loads that DB cache (≤12h old by default) for a whole universe in one call before a scan's per-ticker loop runs — call sites: `/api/scan` and `/api/sector-pulse` in `engine/main.py`. This prefetch existed only in the legacy Streamlit UI (`stock_scanner/ui.py::_run_scan_fragment`) until it was ported here; before that, every FastAPI-driven scan hit yfinance live for `.info`/`.news`/`.calendar`/`.earnings_dates` — 4 requests per ticker — on every single run, and a failed fetch (e.g. yfinance rate-limiting) silently cached a blank entry for the rest of the process's uptime with no log line at all. Both gaps are fixed: failures now log a warning, and the DB cache is actually consulted.

---

### 2.2 Trend Structure (Technical Foundation)
**Max contribution: +65 points**

```python
tech_base        = price > ema200 AND supertrend_direction == 1
perfect_alignment = price > ema20 > ema50 > ema200 AND supertrend == 1
mtf_aligned      = price > weekly_ema30  (multi-timeframe)
```

| Signal | Points | Rationale |
|---|---|---|
| `tech_base` (above EMA200 + Supertrend bullish) | **+50** | EMA200 is the primary institutional trend line. Price above it means long-term structure is intact. Supertrend(10,3) confirms short-term momentum direction. This is the gating condition — stocks that fail this cannot score above ~30. |
| `perfect_alignment` (EMA stack: 20 > 50 > 200 + Supertrend) | **+15** | Full EMA alignment confirms multi-period momentum without gaps. Historically, stocks with all three EMAs stacked in order show significantly better forward returns. |

**Stop-loss derivation (parallel with conviction):**
```python
sl_distance = ATR(14) × (1.5 / adaptive_mult)
sl_price    = price − sl_distance
```
ATR-based stop adapts to volatility rather than using a fixed % — tighter in Bull regimes, wider in Bear to avoid shakeouts.

---

### 2.3 ADX — Trend Strength
**Contribution: −15 to +15 points**

ADX (Average Directional Index, 14-period) measures *how much* the market is trending, without regard to direction.

| ADX Value | Points | Rationale |
|---|---|---|
| ≥ 30 | **+15** | Strong confirmed trend. ADX above 30 historically produces the most reliable trend-following returns. |
| 25–29 | **+12** | Trend building. Momentum is accumulating. |
| 20–24 | **+5** | Emerging trend. Market is transitioning from chop to trend — early entry zone. |
| < 20 | **−15** | Choppy/trendless. Mean-reverting environment. Trend-following signals have low reliability. |

**Why the dead zone was eliminated:** The original code had no signal for ADX 20–25, creating a scoring cliff where a stock could move from +12 to −15 with just a 6-point ADX drop. The 20–24 tier smooths this transition.

---

### 2.4 52-Week High Distance
**Contribution: −10 to +15 points**

```python
distance_to_high_pct = ((52w_high − price) / price) × 100
```

| Distance | Points | Rationale |
|---|---|---|
| < 5% | **+15** | Near ATH breakout zone. "Stocks making new highs tend to make more new highs" — Minervini/O'Neil principle. Minimal overhead resistance. |
| 5–15% | **+8** | Healthy consolidation. Stock is pulling back from recent highs, constructive base-building. |
| 15–35% | **0** | Neutral. Meaningful overhead resistance but not extreme. |
| > 35% | **−10** | Heavy overhead resistance. Requires significantly more buying interest to recover. |

---

### 2.5 Relative Strength vs Nifty 50
**Contribution: −10 to +18 points**

```python
rs_score = stock_30d_return − nifty_30d_return
```

| Outperformance | Points | Rationale |
|---|---|---|
| > +5% | **+18** | Strong outperformer. Stock is attracting capital while peers do less. |
| 0 to +5% | **+8** | Mild outperformer. Slightly above-market momentum. |
| −3% to 0 | **0** | Tracking market. No additional edge. |
| < −3% | **−10** | Underperforming meaningfully. Relative weakness is a red flag even if absolute price is up. |

**Multi-horizon RS (context sub-score input):**
```python
rs_3m  = stock_return_63d  / nifty_return_63d
rs_6m  = stock_return_126d / nifty_return_126d
rs_12m = stock_return_252d / nifty_return_252d
rs_composite = (rs_3m × 0.5) + (rs_6m × 0.3) + (rs_12m × 0.2)
```
Weighted towards recent momentum (3M = 50%) but validates sustainability via 6M and 12M. `rs_composite > 1.0` means the stock outperformed Nifty across the composite horizon.

---

### 2.6 Volume & Breakout Confirmation
**Contribution: −25 to +10 points**

```python
vol_surge_ratio = current_volume / avg_volume_20d
vol_surge       = vol_surge_ratio > 1.5
breakout        = price > 20d_high  (prior 20 bars, excluding today)
```

| Signal | Points | Rationale |
|---|---|---|
| Volume surge (>1.5× avg) | **+10** | Institutional participation. Volume is the fuel behind price moves. |
| Breakout with LOW volume | **−25** | A price breaking above resistance without volume is likely a "volume trap" — institutions aren't buying. High penalty because it's an actionable false signal. |

---

### 2.7 Volatility Contraction (VCP)
**Contribution: +3 to +20 points**

VCP (Volatility Contraction Pattern) is Mark Minervini's framework where a stock builds a base by progressively contracting its range and volume before a breakout.

```python
is_coiling = ATR(14) < ATR(100) × 0.6  AND  avg_volume_5d < avg_volume_20d
```

| Context | Points | Rationale |
|---|---|---|
| Coiling **in uptrend** (`tech_base=True`) AND within 30% of 52w high | **+20** | Highest-quality VCP setup. The stock is base-building near recent highs with shrinking volatility — classic pre-breakout structure. |
| Coiling without uptrend context | **+5** | Volatility contraction in a downtrend often means distribution, not accumulation. Partial credit only. |
| Mild contraction (ATR < 80% of ATR100) without full coil | **+3** | Some volatility reduction, less conviction. |

**Why gated on uptrend:** In bear trend, coiling can mean sellers are exhausted but buyers haven't arrived yet. In uptrend near highs, coiling almost always represents base-building before continuation.

---

### 2.8 Over-Extension Guard
**Contribution: −40 points max**

```python
extension_ema50_pct  = ((price − ema50) / ema50) × 100
extension_ema200_pct = ((price − ema200) / ema200) × 100
```

| Condition | Points | Rationale |
|---|---|---|
| EMA50 extension > 15% | **−20** | Parabolic move above recent moving average. Mean reversion risk is high. Also sets verdict to `⚠️ OVEREXTENDED`. |
| EMA200 extension > 40% | **−20** | Extreme deviation from long-term trend. Historically, stocks this far above EMA200 have a high reversal probability in the short to medium term. |

---

### 2.9 Analyst Dispersion
**Contribution: −10 points**

```python
dispersion_pct = ((target_high − target_low) / price) × 100
dispersion_alert = "⚠️ High Dispersion" if dispersion_pct > 30%
```

| Condition | Points | Rationale |
|---|---|---|
| Analyst target range > 30% of current price | **−10** | High disagreement among analysts signals unclear business trajectory, making the stock harder to value. |

---

### 2.10 War/News Resilience & Gap Integrity

**Resilience** measures if the stock can hold above EMA200 during a severe intraday drop:
```python
drop = prev_close − curr_low
if drop > 2 × ATR(14):
    if price > ema200 → "🛡️ HOLD (Shakeout)"  
    else             → "💀 FAIL (Breakdown)"  score_mod −= 40
```

**Gap Integrity** flags dangerous gap-down opens:
```python
if curr_open < prev_close:
    if curr_open > ema200 AND gap_size < 1.5 × ATR → "✅ Integral"
    else → "⚠️ Gap Risk"
```

These are informational fields displayed to the user. Resilience breakdown triggers a −40 `score_mod`, and that penalty is applied once in the final raw-conviction aggregation so it affects both trend and non-trend setups without double-counting.

---

### 2.11 News Sentiment & Black Swan Detection
**Contribution: −40 to 0 points**

```python
_BLACK_SWAN_TERMS    = {"fraud", "investigation", "default", "bankruptcy", "scam",
                        "class action", "sebi notice", "ed raid", "fir filed", "money laundering"}
_FALSE_POSITIVE_GUARDS = {"victory", "compliance", "cleared", "acquit", "legal win", "no wrongdoing"}

combined_text = join(title + summary for last 10 news items)
```

**Why false-positive guards:** "Legal victory", "compliance cleared", "acquitted" — common positive legal outcomes — were previously triggering the Black Swan flag because the code matched any occurrence of "legal". This generated false negatives for companies that had actually won legal battles.

| Result | Points |
|---|---|
| Black Swan confirmed | **−40** (`score_mod`), `news_sentiment = "🚨 BLACK SWAN"` |
| Clean news | 0 |

---

### 2.12 Earnings Calendar Risk
**Contribution: −20 points**

```python
days_to_earnings = (next_earnings_date − today).days
if 0 ≤ days_to_earnings ≤ 7:
    event_status = "🚨 EARNINGS (DD-Mon)"
    score_mod −= 20
```

**Why:** Holding a position into earnings carries binary event risk that invalidates all technical analysis. A 7-day warning allows the user to either tighten stops or avoid entry entirely. Like the Black Swan and resilience penalties, this adjustment is accumulated once and applied once in the final conviction pass.

---

## 3. Phase 2 — Sub-Score Computation (Raw Components)

These are the four raw dimension scores, computed per-stock alongside conviction, and later normalized in Phase 3.

---

### 3.1 Technical Raw
**Range: 0–68 (before normalization)**

| Component | Points | Condition |
|---|---|---|
| Trend base | +35 | `price > ema200 AND supertrend == 1` |
| RSI in sweet spot | +15 | RSI 45–65 |
| RSI acceptable | +8 | RSI 40–45 or 65–72 |
| Volume surge | +10 | `vol_surge_ratio > 1.8` |
| VCP coiling | +8 | `is_coiling == True` |
| EMA200 over-extension | −20 | `extension_ema200_pct > 40%` |

**Why RSI 45–65 is ideal:** RSI below 40 signals weak momentum; above 72 signals potential exhaustion. The 45–65 zone represents healthy, sustainable momentum — neither oversold nor overbought.

---

### 3.2 Fundamental Raw
**Range: 0–55 (before normalization)**

| Component | Points | Condition |
|---|---|---|
| Base | +30 | Always |
| Analyst upside | ±25 (capped) | `(target_mean − price) / price × 100`, capped at 25 pts max, floored at −20 pts |
| Large cap premium | +10 | `market_cap > ₹1,500 Cr` |
| High dispersion discount | ×0.7 | `analyst_dispersion > 25%` |

**Why clamp analyst upside at ±25:** Analyst targets for small-caps or high-growth names can be wildly optimistic (+200% targets). An uncapped score would let fundamental_raw dominate the weighted blend. Capping at +25 ensures analyst consensus adds useful signal without overpowering technical evidence.

---

### 3.3 Sentiment Raw
**Base: 50.0**

| Component | Points | Condition |
|---|---|---|
| Black Swan | −50 | Confirmed bad news event |
| Earnings beat > 20% | +15 × decay | Strong positive surprise |
| Earnings beat 5–20% | +8 × decay | Moderate beat |
| Earnings in-line / no data | +5 × decay | Neutral |
| Earnings miss 0–20% | −12 × decay | Small disappointment |
| Earnings miss > 20% | −25 × decay | Significant miss |

**Decay formula:**
```python
decay = 0.5 ^ (days_since_earnings / 5.0)
```
Half-life of 5 days — earnings surprise loses 50% of its influence every 5 days. After 20 days the effect is < 7%.

**Why graduated (not binary):** The old code applied −15 for *any* miss, treating a −0.5% miss the same as a −50% collapse. Graduation means the model distinguishes between companies that narrowly missed vs those that catastrophically did.

---

### 3.4 Context Raw
**Range: 0–90 (before normalization)**

| Component | Points | Condition |
|---|---|---|
| Base | +30 | Always |
| MTF alignment | +20 | `price > weekly_ema30` (weekly chart aligned) |
| RS outperformance | +20 | `rs_composite > 1.0` |
| Vol-adjusted momentum | ±20 | `(6m_return / ATR)`, capped ±20 |

**Vol-adjusted momentum (Sharpe-like):**
```python
vol_adj_mom = ret_6m / ATR
```
A 20% 6-month return on a low-ATR stock is more reliable than the same return on a high-ATR volatile stock. Dividing by ATR normalizes returns for volatility.

---

## 4. Phase 3 — Universe-Relative Normalization (`apply_advanced_scoring`)

**Function:** `apply_advanced_scoring(df, scoring_config)`  
Applied to the *entire scan universe batch* — not per stock in isolation.

---

### 4.1 Sector Z-Score Adjustment

Before normalization, each stock's RSI and conviction score is compared to its sector peers:

```python
rsi_z        = (rsi − sector_mean_rsi) / sector_std_rsi     [clipped to ±2σ]
conviction_z = (score − sector_mean_score) / sector_std_score [clipped to ±2σ]
Context_Raw += (rsi_z + conviction_z) × 5.0
```

**Why clipped at ±2σ:** Outliers (e.g., a stock with RSI 85 when its sector averages 55) would inject +15 into Context_Raw uncapped, distorting rankings. Clipping ensures no single outlier dominates cross-sector comparison.

**Purpose:** A stock with RSI 60 in a sector where the average is 45 is more notable than the same RSI in a sector already at 60. Sector-relative scoring surfaces this edge.

---

### 4.2 IQR Normalization

All four sub-scores are normalized to 0–100 using IQR-based winsorization:

```python
q1, q3 = series.quantile([0.25, 0.75])
iqr = q3 − q1
clipped = series.clip(q1 − 1.5×iqr, q3 + 1.5×iqr)
normalized = (clipped − min) / (max − min) × 100
```

**Why IQR not min-max:** Simple min-max normalization is distorted by a single extreme outlier. IQR winsorization compresses tails, making the 0–100 range reflect the realistic distribution of the scanned universe. Stocks outside the whiskers are clamped, not excluded.

---

### 4.3 RS Rank Bonus

```python
rs_rank = rs_base.rank(pct=True) × 100   (percentile within universe)
if rs_composite > 1.0 OR rs_rank >= 75th percentile:
    Context_Score += 20  [capped at 100]
```

**Why two conditions (OR):** Some stocks may have a composite RS just under 1.0 but rank in the top quartile — they've outperformed most of the universe even if not the raw Nifty. The OR ensures either signal qualifies the bonus.

---

### 4.4 Sector Rotation Bonus

```python
top_sectors = top 3 sectors by mean 90-day return across scanned universe
if stock.sector in top_sectors:
    Context_Raw += 10  (SECTOR_ROTATION_BONUS_POINTS)
```

**Purpose:** Capital rotates between sectors. A stock in a hot sector gets a tailwind bonus because institutional flows are more likely to support it regardless of individual fundamentals.

---

### 4.5 Weighted Score Composition

```python
Score_Pre_Regime = (
    Technical_Score  × weight_technical   +
    Fundamental_Score × weight_fundamental +
    Sentiment_Score  × weight_sentiment   +
    Context_Score    × weight_context
)
```

**Default weights:**
| Dimension | Default | Rationale |
|---|---|---|
| Technical | 50% | Price action is the primary signal in swing trading |
| Fundamental | 25% | Validates structural business quality |
| Sentiment | 15% | News/earnings can override technical signals temporarily |
| Context | 10% | Market regime and RS add a second-order filter |

Weights are fully configurable per-scan. All weights are normalized to sum to 1.0 regardless of user input.

---

## 5. Phase 4 — Regime Multiplier

### 5.1 Regime Detection Logic (`pulse.py`)

Called via `fetch_market_pulse_data()` (Streamlit, cached 60s) or `get_current_regime()` (FastAPI, uncached).

**Inputs:** Nifty 50 (`^NSEI`), India VIX (`^INDIAVIX`) — 1 year of daily data.

```python
nifty_ema200 = EMA(nifty_close, 200)
nifty_ema50  = EMA(nifty_close, 50)
vix_val      = latest India VIX close
```

### 5.2 5-Tier Regime Table

| Regime | Trigger | Multiplier | Interpretation |
|---|---|---|---|
| 🟢🟢 **Strong Bull** | EMA50 > EMA200 (golden cross) AND Nifty > EMA200 AND VIX < 15 | **1.25×** | Ideal conditions. All systems go. Risk-on. |
| 🟢 **Bull** | Nifty > EMA200 AND VIX ≤ 20 | **1.10×** | Normal uptrend. Take trades with normal sizing. |
| 🟡 **Range** | Neither strongly bull nor bear | **1.00×** | Neutral. Selective entries. |
| 🟠 **Caution** | Nifty < EMA200 OR VIX > 25 | **0.80×** | Reduce exposure. Only highest conviction trades. |
| 🔴 **Bear** | Nifty < EMA200 AND VIX > 30 | **0.65×** | Capital protection mode. Minimal longs. |

```python
Score = Score_Pre_Regime × Regime_Multiplier   [clipped 0–100]
```

**Why EMA50 cross matters for Strong Bull:** A Golden Cross (EMA50 crossing above EMA200) has historically preceded sustained bull phases in Indian markets. It's a stronger signal than simply being above EMA200.

---

## 6. Phase 5 — Quality Gates

**Function:** `_apply_quality_gates(df, cfg)`

These are **binary hard filters** — fail any gate and the stock is penalized, not disqualified. This allows the scanner to still show the stock but clearly mark it as problematic.

| Gate | Condition (FAIL if) | Default | Rationale |
|---|---|---|---|
| Liquidity | Avg daily value < threshold | ₹8 Cr | Illiquid stocks have high impact cost, slippage risk, and can't be exited quickly in adverse conditions. |
| Price | Price < threshold | ₹80 | Very low-priced stocks attract retail speculation, have erratic price behaviour, and are vulnerable to operator activity. |
| Market Cap | Known market cap > 0 and < threshold | ₹1,500 Cr | Below this, institutional coverage drops sharply, analyst targets are unreliable, and corporate governance risk rises. Missing metadata does not trigger this hard fail. |
| Debt/Equity | D/E ratio > threshold | 2.0 | High leverage amplifies losses in downturns and increases bankruptcy risk. |
| Liquidity Flag | `Liquidity_Flag == "Low Liquidity - Avoid"` | — | Explicit override from pre-computed liquidity analysis. |

**Penalty on fail:**
```python
Score = max(0, Score − 1000)   # Effectively zeros the score
Verdict = "❌ FAIL"
```

**Why subtract 1000 instead of set to 0:** The current normalization structure means score 0 could overlap with a legitimate low scorer. Subtracting 1000 before the final `clip(0, 100)` produces a clean 0 guaranteed to be below all passing stocks, while preserving the original pre-gate score in `Score_Pre_Regime` for transparency.

**Important:** The raw conviction fallback only runs when the core conviction is still zero. In that case it uses the base estimate plus any accumulated `score_mod`, so explicit risk penalties still matter even when the trend gate never activated.

**UI note:** The stock screener table displays the `Score` column as `Conviction Score`. The display mapping lives in [`engine/stock_scanner/ui_helpers.py`]( /Users/shivamdixit/Desktop/fortress-dashboard/engine/stock_scanner/ui_helpers.py ) so the table rename logic can be tested without importing the full Streamlit app. When `ENABLE_NEW_FEATURES` is on and the AI score toggle is enabled, `ai_score` is shown separately as `AI Score`.

**Note:** All gate thresholds use strict `<` / `>` operators. A stock at exactly the threshold *passes* — this prevents border-case stocks from being incorrectly disqualified.

---

## 7. Final Verdict Logic

The verdict is applied **after** regime adjustment and quality gates:

| Verdict | Condition |
|---|---|
| `🚨 AVOID` | Black Swan flag triggered |
| `❌ FAIL` | Any quality gate failed |
| `⚠️ OVEREXTENDED` | EMA50 extension > 15% |
| `🔥 HIGH` | Score ≥ 85 AND MTF-aligned |
| `🚀 PASS` | Score ≥ 60 |
| `🟡 WATCH` | Score < 60 but `tech_base == True` |

> **Note:** AVOID and FAIL override HIGH — a Black Swan always shows as AVOID regardless of technical score.

---

## 8. Weight Configuration

Users can customize the four dimension weights via the Screener sidebar. All weights are auto-normalized to sum to 1.0:

```python
# Example: Technical-heavy config
weights = {"technical": 0.70, "fundamental": 0.15, "sentiment": 0.10, "context": 0.05}

# Example: Fundamental-driven config
weights = {"technical": 0.30, "fundamental": 0.50, "sentiment": 0.10, "context": 0.10}
```

Additional scan parameters:
| Parameter | Default | Effect |
|---|---|---|
| `liquidity_cr_min` | ₹8 Cr | Minimum daily traded value gate |
| `market_cap_cr_min` | ₹1,500 Cr | Minimum market cap gate |
| `price_min` | ₹80 | Minimum price gate |
| `enable_regime` | True | If False, uses 1.0× multiplier regardless of market |

---

## 9. Scoring Flow Diagram

```
          yfinance OHLCV (1y)
                  │
    ┌─────────────▼──────────────────────────────────────┐
    │  check_institutional_fortress()              Phase 1│
    │                                                     │
    │  [Trend] EMA200 + Supertrend + EMA stack            │
    │  [ADX]   Trend strength tier                        │
    │  [52W]   Distance to high tier                      │
    │  [RS]    30D vs Nifty (tiered)                      │
    │  [Vol]   Surge + Breakout confirmation              │
    │  [VCP]   Coiling (gated on uptrend context)         │
    │  [Guard] Over-extension check                       │
    │  [News]  Black Swan detection                       │
    │  [Earn]  Calendar risk                              │
    │                                                     │
    │  → raw conviction (0–100)                           │
    │  → technical_raw / fundamental_raw / sentiment_raw  │
    │  → context_raw                                      │
    └─────────────────────────────────────────────────────┘
                  │ (batch DataFrame)
    ┌─────────────▼──────────────────────────────────────┐
    │  apply_advanced_scoring()           Phases 3, 4, 5  │
    │                                                     │
    │  [Sector Z-score] RSI + conviction vs sector peers  │
    │  [IQR Normalize]  technical/fundamental/sentiment/  │
    │                   context → 0–100 each              │
    │  [Sector Bonus]   Top 3 sectors by 90D return +10   │
    │  [RS Rank Bonus]  Top quartile RS → Context +20     │
    │  [Weighted blend] T×wT + F×wF + S×wS + C×wC        │
    │  [Regime ×mult]   Bull 1.10x … Bear 0.65x          │
    │  [Quality Gates]  Liquidity / Price / MCap / D/E    │
    │                                                     │
    │  → Final Score (0–100)                              │
    │  → Verdict emoji                                    │
    └─────────────────────────────────────────────────────┘
```

---

## 10. Design Decisions & Rationale

### Why not a pure ML model?
The system intentionally uses a rule-based scoring framework rather than a trained ML model. Reasons:
1. **Explainability** — every point can be traced to a specific signal
2. **No look-ahead bias** in backtesting (sub-scores use only historical data)
3. **Domain-knowledge encoding** — Minervini's VCP, Nifty RS, ADX filters are battle-tested institutional-grade criteria
4. **Reproducibility** — same inputs always produce same scores

### Why EMA200 as the primary gate?
EMA200 is the most widely watched indicator across institutional desks globally. Its self-fulfilling nature makes it reliable — large fund managers set buy programs above EMA200 and stop-losses below it. This creates real support/resistance at EMA200 regardless of the underlying fundamentals.

### Why is RS vs Nifty better than absolute return?
A stock that gained 12% in a month where Nifty gained 15% is actually underperforming. Relative strength isolates alpha from market beta and identifies stocks attracting excess buying beyond general market drift.

### Why graduated earnings surprise?
Original logic: `if miss: −15`. This treats a company that missed by 0.1% the same as one that missed by 50%. The graduated model (−12 for small miss, −25 for large miss) reflects the market's actual reaction — small misses are often forgiven while large misses trigger sustained selling.

### Why cap the regime multiplier effect?
The `clip(0, 100)` after multiplier application means even in a Strong Bull (1.25×), a score of 90 becomes min(112.5, 100) = 100. This prevents the multiplier from making every stock look exceptional in bull markets and keeps scores meaningful across regime changes.

---

*For questions on the scoring engine, refer to `engine/stock_scanner/logic.py` (conviction + sub-scores), `engine/stock_scanner/pulse.py` (regime), and `engine/stock_scanner/config.py` (column definitions for UI display).*

---

## Regression Coverage

The historical ad-hoc conviction repro scripts have been converted into pytest coverage under `tests/backend/test_conviction_regressions.py`. These tests protect the key scoring invariants that caused prior branch noise: positive conviction scores must survive advanced scoring, zero and positive cases must remain differentiated, identical raw-score universes must not collapse to `0`, and uptrend candidates must outrank downtrend candidates when all quality gates pass.
