# Fortress user guide

## 1. What is Fortress?

Fortress is a personal research system for examining Indian stocks, mutual
funds, listed trusts, US instruments, commodities, and options; recording
orders and picks; and observing simulated paper-trade outcomes. Its outputs are
decision support. A score, label, confidence level, or successful historical
observation does not predict or guarantee a future result.

## 2. Getting started

The root route sends an authenticated user to **Dashboard** and everyone else
to **Login**. Login has **Login**, **Sign Up**, and **Guest** tabs. Guest access
is useful for exploration when the server permits it. The authenticated desktop
layout shows the full sidebar. On a narrow screen, press **Open menu**, choose a
page, and the menu closes.

System status in the sidebar reports whether the API health check succeeds. A
failure means pages may show empty or retry states; it does not mean an
investment signal is negative. **Logout** ends the current session.

The **Help** button opens the ten-step product tour. The tour never starts by
itself, supports Next, Back, Skip, Finish, Escape, and arrow keys, and can be
restarted. Completion is stored only in this browser.

## 3. Dashboard

**Use it for:** an account-level starting point.

**What you see:** account/profile statistics, a profile snapshot, and recent
orders. These are summaries of saved user data, not market analysis.

**What you can click:** use the sidebar to continue to Orders, Profile, or a
research section. An empty recent-orders table means no matching saved records;
it is not an API success guarantee if the page also reports an error.

## 4. Stock Screener

**Use it for:** read-only single-symbol lookup or a broader, persisted universe
analysis.

**Controls and flow:**

1. In **Search a Stock**, enter a symbol or company name and select a match.
   Search is read-only. A returned symbol can be opened in **Options**.
2. For a scan, choose the available **Universe**, price-data source, and broker
   context. Universe names come from the server and can vary.
3. **Run Scan** creates an analysis job. Progress stages can include queued,
   fetching, scoring, persisting, completed, or failed. Because a scan can be
   expensive and writes history, only trigger one intentionally.
4. Review structured results and select a row where offered. Typical fields
   include Symbol, Strategy, Quality Gate, Fortress Score, technical indicators,
   component scores, risk flags, sector/regime context, and data quality.

**Fortress Score:** a rule-based 0–100 conviction summary of available inputs.
It is not “percent chance of profit.” A high score can coexist with risk flags,
stale data, or weak historical evidence. Component scores explain contributing
technical, fundamental, sentiment, and context inputs.

**Signal versus Oracle:** a screener signal is the current rule-based
observation. **Oracle Decision** is a separate evidence-aware layer available
for a persisted signal. It returns POSITIVE, NEUTRAL, NEGATIVE, or UNAVAILABLE,
a HIGH/MEDIUM/LOW confidence label, reasons, cautions, version, and data-as-of
context when the backend has it. Oracle is not presented as AI, does not predict
the future, and its confidence is not a success probability.

**History and evidence:** **Scan History** replays what was persisted at a past
run. Historical Evidence describes outcomes for comparable past observations,
with horizon and sample size. It remains separate from the current score.
Illustrative fixture evidence is explicitly labelled and must not be treated as
model-derived evidence.

**Common confusion:** provider selection, a completed HTTP request, and a
visible result are different truths. Check freshness/data-quality labels. A
missing sector pulse or evidence panel is not automatically a failed scan.

## 5. Scan History

**Use it for:** reviewing persisted, read-only results—not rerunning a scan.

1. Choose a scanner tab such as **Stocks**. Tabs exist only for scan types
   returned by history data (Stocks remains the default section).
2. Runs in that section show date, time, universe coverage, number analysed, and
   a **COMPLETE** badge. Current history records do not expose running/failed
   entries in this view; COMPLETE means the stored run finished, not that every
   optional field is available.
3. Select a run. Stocks open **Historical Stock Screener**, preserving
   stock-specific concepts and associated signal/paper-trade provenance. Other
   types use a labelled historical table rather than mixing all timestamps.
4. Select **Back to Scan History** to return to the current section. The chosen
   section is also kept in the URL/browser storage for a useful return path.

Loading, no-scans, data-load failure, and optional-context failure are separate
states. Retry is offered for critical list/result failures. Optional historical
context can be absent while the persisted scan rows remain usable.

## 6. Oracle decisions

Oracle is contextual rather than a top-level route. Open it from a recorded
signal where the **Oracle Decision** control appears.

- **Decision** summarizes the evidence layer: POSITIVE supports further
  investigation, NEUTRAL is mixed, NEGATIVE is cautionary, and UNAVAILABLE
  means a decision could not be supported.
- **Confidence** indicates the strength/completeness of evidence used by the
  decision layer; it is not the probability of a gain.
- **Reasons** support the label; **Cautions** constrain it.
- **Data as of** and version identify the evidence context.
- A Fortress Score is a current rule-based signal input. Oracle is a distinct
  decision record. Neither is a trade instruction.

## 7. Paper Trading

**Use it for:** simulated learning with recorded eligible Fortress signals.
This page does not submit real broker trades.

The lifecycle is: eligible signal → user-confirmed **Open PAPER TRADE** → open
paper position → monitoring/valuation → user-confirmed close → closed result.
An open position has an entry, quantity/notional, current valuation where
available, unrealized P&L, status, and source signal. Closing records the exit
and turns the return into a realized historical observation.

Rows and cards expose recent eligible signals, **Open PAPER Positions**, and
**Closed PAPER Trades**. Select a trade for detail. Opening/closing changes
saved simulation data and was deliberately not exercised against a live
backend during the documented walkthrough. Empty, loading, and retryable error
states were exercised with safe fixtures.

A paper-trade win is one observation, not proof of a strategy. Review sample
size, costs/assumptions, holding period, benchmark context, and drawdown.

## 8. Mutual Fund Lab

**Use it for:** comparing the currently returned scheme analysis.

The page shows fund count, average/high conviction, stale-data count, category
and subcategory filters, a full table, and a conviction grid. Select a fund row
or card to see conviction breakdown, confidence, risk flags, and data quality.
Displayed metrics depend on server data and may include NAV, returns, alpha,
beta, volatility, Sharpe/Sortino, drawdown, category, and scheme identifiers.

**Job Controls** (NAV sync, full recalculation, scheme discovery, or metric
update; optional scheme codes and force refresh) mutate analysis state and may
be expensive. They were not run in the live walkthrough. They are operational
controls, not ordinary browsing controls.

“High conviction” is a model threshold, not low risk. Missing and stale data
must be read alongside the score. The current UI does not provide a dedicated
fund comparison basket, SIP calculator, lump-sum calculator, portfolio-overlap
workflow, or separate Indian ETF page; do not infer those features from common
fund terminology.

## 9. ETFs

Fortress currently exposes **US ETFs inside US Investing**, distinguished from
US stocks by an ETF badge and asset class. Details may show price, USD/INR
conversion, returns, volatility, drawdown, P/E/P/B where meaningful, dividend
yield, beta, average volume, expense ratio, and AUM. There is no first-class
Indian ETF page or tracking-error comparison flow in the current navigation.

An ETF trades like a stock but represents a basket. A mutual fund is transacted
through the fund structure, usually at NAV rather than continuously on an
exchange. An individual stock is ownership in one company.

## 10. REITs & InvITs

**Use it for:** discovering listed real-estate and infrastructure trusts.
Search by name/symbol, filter type, change sort direction/metric, open a row for
key metrics, add/remove a watchlist item, or open the symbol in Options context.
The page can show price/NAV relationship, distribution yield and history,
occupancy or WALE for applicable trusts, leverage/debt measures, DPU, returns,
risk flags, score, confidence, and freshness when supplied.

A high distribution yield can reflect higher risk or a falling market price.
Premium/discount to NAV is descriptive, and REIT/InvIT score is decision
support—not a promised distribution or capital return. **Refresh** changes
cached analysis and was not triggered in the live walkthrough.

## 11. US Investing

**Use it for:** discovering the supported US stock/ETF universe. Search, filter
sector, choose sort, reverse sort direction, include INR display, select a row,
use watchlist controls, and open Options context. Details expose available
price, return, volatility, drawdown, valuation, yield, beta, volume, market cap
or ETF expense ratio/AUM.

USD returns and INR-converted values answer different questions. INR value is
sensitive to the USD/INR rate, so currency movement can increase or reduce an
Indian investor’s return even when the US instrument price is unchanged. The
page is research only; it does not document tax, remittance, legal eligibility,
or brokerage execution. **Refresh** was not triggered live.

## 12. Options

**Use it for:** inspecting a provider snapshot and modelling expiry payoff. It
does not place orders or estimate probability of profit.

1. Choose **Underlying**, **Expiry**, and **OI Threshold**; then **Load Chain**.
2. Check provider, freshness, last updated, spot, nearest available ATM strike,
   Put/Call OI, highest call/put OI, capability truth, and diagnostics.
3. Read **Chain Snapshot** fields: strike, call/put type, moneyness, last traded
   premium, OI/change in OI, volume, IV, bid, and ask. “Unavailable” is more
   honest than an inferred value.
4. **What Changed?** requires two successful snapshots. Without them it reports
   insufficient history rather than manufacturing a comparison.
5. In **Strategy Lab**, load a long call, long put, long straddle, or call
   spread; edit BUY/SELL, CE/PE, strike, premium, add a leg, choose range, and
   calculate. This is explicit, read-only expiry analysis.

The payoff table shows P&L only for the evaluated underlying-price range.
**Theoretical max profit/loss** and breakevens are reported separately by the
engine and can be bounded, unbounded, or unavailable. Never interpret the best
or worst displayed grid point as a stronger theoretical claim. The Legacy
Strategy Scanner is descriptive and explicitly not a recommendation or full
risk model.

## 13. Commodities, Orders, Picks, and Profile

**Commodities** compares available commodity rows, descriptive decision cards,
returns, and conviction/spread heatmap. Refresh can request new provider data
and was not run live.

**Orders** is a user-maintained log with symbol, type, status, quantity, price,
broker, and notes plus status/broker filters. “Log Order” writes a record; it is
not proof of broker execution. No order was created during the walkthrough.

**Picks Tracker** records monitored ideas, strategy text, and outcome states,
then summarizes hits, misses, expiry/trailing results and P&L where recorded.
Creating a pick changes saved data and was not tested live.

**Profile & Settings** shows account data and broker connections. Connecting or
disconnecting a broker changes credentials/settings and was not tested. Never
paste credentials into an untrusted environment.

## 14. Research and evidence

Keep these layers separate:

- **Current signal:** what current rules observed.
- **Oracle decision:** a persisted decision label with reasons/cautions.
- **Historical observation:** what a previous run stored.
- **Paper-trade result:** one simulated position outcome.
- **Research evidence:** aggregated outcomes for a defined horizon/cohort.
- **Forward evidence:** outcomes measured after a signal, avoiding hindsight.

Sample size says how many observations support a statistic. Confidence describes
evidence quality, not certainty. Benchmark excess return compares observations
with a reference. One successful signal is not a proven strategy, and historical
performance does not guarantee future performance.

## 15. Common workflows

### Research a stock without mutation
Dashboard → Stock Screener → symbol search → inspect current score/data quality
→ Oracle Decision when available → Historical Evidence → Scan History for the
persisted run. Opening Options context remains read-only until payoff is
calculated.

### Replay history
Scan History → select section → select dated run → inspect section-specific
results → Back to Scan History. This was verified for Stock and Mutual Fund
fixture records; only Stock has the specialized historical layout.

### Follow a simulated idea
Recorded eligible signal → Oracle Decision → Paper Trading → Open PAPER TRADE →
Open PAPER Positions → close later → Closed PAPER Trades/evidence. The route and
empty/detail UI were verified safely; live open/close mutations were not.

### Compare asset classes
Mutual Fund Lab for returned schemes; REITs & InvITs for listed trusts; US
Investing for US stocks/ETFs; Commodities for commodity rows. Scores across
sections may use different inputs and should not be treated as interchangeable.

## 16. Troubleshooting

- **Initializing Fortress never finishes:** authentication/profile API may be
  unavailable. Reload once; if it persists, check service status.
- **Couldn’t load / Retry:** the critical request failed. Retry once. Preserve
  the exact user-facing message for support; normal UI should not expose a stack
  trace.
- **Empty table:** can mean a valid empty dataset. It differs from an error card.
- **No historical scans/open positions:** create data only if intentional and
  safe; do not trigger work merely to remove an empty state.
- **Options unavailable:** choose an available expiry, lower a filtering
  threshold only if meaningful, and read provider diagnostics. Comparison needs
  two successful snapshots.
- **Stale/partial data:** reduce confidence and verify freshness externally;
  never treat a missing value as zero.
- **Session expired:** return to Login. Unsaved form entries may be lost.
- **Mobile table:** horizontally scroll wide financial tables; use the menu
  button to change pages.

## 17. Glossary

Use the [Fortress Glossary](GLOSSARY.md). Contextual ⓘ help is provided for
Fortress Score, Oracle Confidence, Open Interest/OI threshold, ATM strike, and
Put/Call OI.

## 18. Limitations and important notes

Fortress does not guarantee returns. Provider availability, freshness, missing
fields, score methodology, and historical sample selection all constrain its
outputs. The walkthrough did not place trades, trigger scans/refresh jobs,
create orders or picks, alter broker connections, or change production data.
Fixture-backed browser tests prove routing and UI behavior, not provider
correctness or investment performance. See the [truth matrix](WALKTHROUGH_STATUS.md).
