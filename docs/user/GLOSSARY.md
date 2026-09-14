# Fortress glossary

This is a product glossary, not a general investing dictionary. Every retained
term is visible in the current Fortress UI, an API-backed result rendered by
it, or necessary to interpret an exposed control. Definitions explain how to
use the product and avoid turning descriptive data into promises.

**Alphabetical jump:** [A](#a) · [B](#b) · [C](#c) · [D](#d) · [E](#e) ·
[F](#f) · [H](#h) · [I](#i) · [L](#l) · [M](#m) · [N](#n) · [O](#o) ·
[P](#p) · [Q](#q) · [R](#r) · [S](#s) · [T](#t) · [U](#u) · [V](#v) ·
[W](#w) · [Y](#y)

## Fortress product terms

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| <a id="c"></a>Confidence | A HIGH/MEDIUM/LOW label or numeric evidence-quality measure, depending on the screen. | It qualifies a score/decision; it is not probability of profit. | Oracle Decision, Data Quality |
| Conviction Score | A section-specific summary of how strongly available inputs align. | Used in fund and asset discovery; compare with its breakdown and flags, not across unlike models. | Fortress Score, Risk Flag |
| Data as of | The time through which inputs were current. | A decision can be correctly displayed but based on older evidence. | Freshness |
| Data Quality | Complete, partial, or stale description of input fitness. | Missing/stale inputs should reduce reliance on a score. | Freshness, Unavailable |
| <a id="f"></a>Fortress Score | A rule-based score from 0 to 100 combining available signal components. | It summarizes current evidence and is neither a probability nor return forecast. | Signal, Component Score |
| Oracle Decision | A persisted POSITIVE, NEUTRAL, NEGATIVE, or UNAVAILABLE evidence-aware decision for a signal. | It is distinct from the raw Fortress Score and includes reasons/cautions. | Confidence, Signal |
| Quality Gate | A rule indicating whether minimum analysis conditions were met. | A pass permits consideration; it does not guarantee quality or return. | Data Quality, Risk Flag |
| Risk Flag | A warning generated from an identified condition or missing/weak input. | Read flags before acting on a high score. | Data Quality, Caution |
| Scanner / Screener | A tool that evaluates a selected universe against Fortress analysis. | “Stock Screener” is the canonical UI name; a scan can create persisted history. | Universe, Scan History |
| Signal | A current recorded observation from analysis rules. | A signal can feed Oracle/evidence/paper trading but is not an order. | Oracle Decision, Paper Trade |
| Universe | The group of instruments a scan evaluates, such as Nifty 50. | It defines coverage; results outside it were not evaluated in that run. | Scan, Coverage |

## Status labels

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| ACTIVE | The account/session is enabled. | It describes account state, not a market position. | Guest Session |
| <a id="b"></a>BULLISH / BEARISH / NEUTRAL | Descriptive upward, downward, or mixed market/signal posture. | It is context, not a guaranteed direction. | Signal, Regime |
| BUY / WATCH / AVOID | Possible result labels for favorable, monitor, or cautionary screening states. | They support triage and are not broker instructions. | Signal, Oracle Decision |
| <a id="e"></a>EXECUTED / PENDING / REJECTED / CANCELLED | User-recorded order statuses. | They categorize the Orders log; a log entry alone does not prove broker execution. | Order |
| COMPLETE / COMPLETED | A scan/history job finished its recorded workflow. | It does not mean all optional data is populated. | Failed, Scan History |
| FAILED | A job/request could not complete. | Use the shown error/retry path; do not treat it as an investment label. | Retry |
| INSUFFICIENT_HISTORY | Too few comparable snapshots/observations exist. | Fortress declines to infer a change or statistic. | Sample Size, Unavailable |
| <a id="h"></a>HIGH / MEDIUM / LOW | Ordinal strength/quality bands. | Meaning depends on the labelled field; HIGH confidence is not certainty. | Confidence, Score |
| <a id="o"></a>OPEN / CLOSED | A simulated paper position is active or has a recorded exit. | Open P&L can change; closed P&L is a completed simulation observation. | Entry, Exit |
| POSITIVE / NEGATIVE / NEUTRAL / UNAVAILABLE | Oracle’s supportive, cautionary, mixed, or unsupported decision labels. | They summarize evidence and never guarantee the next price move. | Oracle Decision |
| QUEUED / RUNNING | A job is waiting or actively progressing. | Wait for completion; navigating away may not cancel backend work. | Scan Stage |
| STALE | Data is older than the product’s freshness expectation. | Treat conclusions cautiously and verify the timestamp. | Freshness |
| UNAVAILABLE | The source cannot responsibly provide a value/decision. | It is not zero and should not be guessed. | Missing Data |

## Stock market and analysis

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| <a id="a"></a>ADX — Average Directional Index | Estimates trend strength, regardless of up or down direction. | It can describe technical strength; it is not a buy/sell rule by itself. | Trend, +DI/-DI |
| ATR — Average True Range | Estimates typical recent price movement, including gaps. | It helps describe volatility/risk and possible price range. | Volatility |
| Benchmark | A reference index or return series. | Excess return only has meaning relative to the stated benchmark. | Excess Return |
| CAGR | Smoothed annual growth rate between a start and end value. | Useful for comparing periods, but hides the path and drawdowns. | Return, Drawdown |
| Component Score | One part of a combined score, such as technical or fundamental. | It explains why a total score is high or low. | Fortress Score |
| Coverage | What instruments/data a run actually examined. | Prevents assuming the scan covered the whole market. | Universe |
| Drawdown / Max Drawdown | Decline from a prior peak; max drawdown is the largest observed peak-to-trough fall. | It shows downside experience that average return can hide. | Risk, Volatility |
| Fundamental | Company/fund characteristics such as valuation or financial quality. | One component of supported analysis, distinct from price signals. | P/E, P/B |
| MACD | A momentum/trend indicator comparing moving averages. | It is one possible technical descriptor, not a standalone prediction. | Momentum, Trend |
| Market Regime | A broad environment classification such as trending or risk-off. | Context can change how a signal is interpreted. | Context Score |
| Momentum | The tendency of price changes to persist over a measured period. | Fortress may use it as evidence; momentum can reverse. | RSI, MACD |
| P/B Ratio | Market price divided by book value per share. | A valuation comparison whose meaning varies by industry. | P/E Ratio |
| P/E Ratio | Market price divided by earnings per share. | It provides valuation context; negative/missing earnings can make it unsuitable. | Earnings, P/B Ratio |
| Relative Strength | Performance compared with a reference or peers. | It describes comparative momentum, not the RSI indicator unless labelled RSI. | Momentum, RSI |
| RSI — Relative Strength Index | A 0–100 momentum indicator comparing recent gains and losses. | Values above 70/below 30 are often called overbought/oversold, but neither is automatically a signal. | Momentum, MACD |
| Sector | A group of businesses with similar economic activity. | Sector filters/pulse show context and concentration. | Sector Intelligence |
| Sentiment | A representation of market attitude from available inputs. | It can contribute to a score but may change quickly. | Component Score |
| Volatility | How widely returns/prices vary. | Higher volatility usually means a wider range of possible outcomes, not automatically poor return. | ATR, Drawdown |

## Risk, return, and research evidence

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| Alpha | Return beyond what a selected benchmark/risk model would imply. | Its meaning depends on benchmark, period, and sample. | Beta, Excess Return |
| <a id="b2"></a>Beta | Sensitivity to movements in a reference market; roughly 1 means similar sensitivity. | It is relative risk context, not a maximum loss estimate. | Alpha, Volatility |
| Evidence Horizon | The future measurement window after a historical signal, such as 20 days. | Results across different horizons should not be mixed. | Forward Return |
| Excess Return | Return minus benchmark return over the same interval. | It shows relative rather than absolute performance. | Benchmark, Alpha |
| Forward Evidence | Outcomes measured after a signal was recorded. | It reduces hindsight bias but still does not prove future performance. | Historical Evidence |
| Forward Return | Price return over a defined period following an observation. | It is historical outcome data, not today’s forecast. | Evidence Horizon |
| Historical Evidence | Aggregated outcomes for comparable past observations. | It must stay separate from the current signal and disclose sample/source. | Sample Size, Win Rate |
| Historical Win Rate | Percentage of defined historical observations meeting the success rule. | It depends on the rule, horizon, sample, and costs; it is not future probability. | Sample Size |
| Median Return | Middle observed return after sorting results. | It is less dominated by extremes than an average. | Forward Return |
| Sample Size | Number of observations behind a statistic. | Small samples make evidence less reliable; Fortress can report insufficient data. | Confidence |
| Sharpe Ratio | Excess return per unit of total return variability. | It supports risk-adjusted comparison but depends on period/assumptions. | Sortino, Volatility |
| Sortino Ratio | Return relative to downside variability. | It focuses on harmful volatility but still depends on inputs and period. | Sharpe, Drawdown |
| Win Rate | Share of completed observations classified as wins. | It omits win/loss size; pair it with expectancy and drawdown. | Expectancy |

## Mutual funds and ETFs

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| <a id="a2"></a>AUM — Assets Under Management | Total value managed by a fund. | It provides scale context, not a quality guarantee. | NAV |
| Category / Subcategory | Peer grouping such as equity and large cap. | Filters make comparisons more like-for-like. | Benchmark |
| Direct / Regular | Direct plans exclude distributor commission; regular plans include distribution arrangements. | Costs can differ, though Fortress does not currently offer a plan-switch workflow. | Expense Ratio |
| ETF — Exchange-Traded Fund | A pooled basket traded on an exchange throughout market hours. | Current UI exposes US ETFs inside US Investing, not a separate Indian ETF page. | Mutual Fund, AUM |
| Expense Ratio | Annual operating cost charged by a fund as a percentage of assets. | Costs reduce investor return; lower is not automatically better overall. | Tracking Difference |
| Growth / IDCW | Growth reinvests gains; IDCW may distribute income subject to the scheme’s policy. | These variants are economically different and should not be compared blindly. | NAV |
| Lump Sum | One-time investment. | It is a glossary distinction only; current UI has no lump-sum calculator. | SIP |
| Mutual Fund | Pooled investment vehicle priced according to its scheme structure. | Mutual Fund Lab analyses returned schemes and metrics. | NAV, ETF |
| <a id="n"></a>NAV — Net Asset Value | Per-unit value of a fund/trust’s assets minus liabilities. | Used for fund valuation and REIT/InvIT premium/discount context. | AUM, Premium/Discount |
| Portfolio Overlap | Proportion of holdings shared by two funds. | High overlap can reduce diversification, but current UI has no overlap workflow. | Diversification |
| Rolling Return | Return calculated repeatedly across overlapping start dates. | It describes consistency better than one chosen start date; only relevant when supplied. | CAGR |
| SIP — Systematic Investment Plan | Regular scheduled fund contribution. | Helps distinguish periodic investing, though current UI has no SIP calculator. | Lump Sum |
| Tracking Difference | Fund return minus index return after costs and effects. | It describes delivered index replication when available. | Tracking Error |
| Tracking Error | Variability of the tracking difference over time. | Lower means more consistent index following; current UI does not expose a dedicated comparison. | Tracking Difference |

## REITs and InvITs

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| Debt / Leverage | Borrowed funding relative to assets/equity or another base. | More leverage can amplify both returns and risk. | Interest Coverage |
| Distribution | Cash paid by a trust to unit holders under its structure. | History and sustainability matter more than one payment. | DPU, Yield |
| Distribution Yield | Recent/expected distribution divided by market price. | A high yield can also reflect falling price or elevated risk. | Distribution, Yield |
| DPU — Distribution Per Unit | Distribution allocated to each trust unit. | It helps compare payout history but is not guaranteed. | Distribution |
| Interest Coverage | Ability of earnings/cash flow to cover interest expense. | Lower coverage can signal debt-service risk. | Debt |
| InvIT — Infrastructure Investment Trust | Listed vehicle holding income-producing infrastructure assets. | InvIT-specific economics differ from company shares and REITs. | REIT, Distribution |
| Occupancy | Share of available property space that is leased. | For applicable REITs it provides operating-demand context. | WALE |
| Premium / Discount to NAV | Market price above/below estimated NAV. | It is descriptive; NAV estimates and market expectations can change. | NAV |
| REIT — Real Estate Investment Trust | Listed vehicle holding income-producing real estate. | Fortress compares supported REIT metrics, payouts, and risks. | InvIT, Occupancy |
| WALE — Weighted Average Lease Expiry | Average remaining lease term weighted by rent/area. | Longer WALE can imply income visibility but does not remove tenant risk. | Occupancy |
| <a id="y"></a>Yield | Income over price/value, expressed as a percentage. | Confirm which income and period the UI uses; yield is not total return. | Distribution Yield |

## US investing

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| Currency Exposure | Return impact from changes between an asset’s currency and the investor’s reference currency. | USD/INR movement can change INR returns independently of the US asset. | USD/INR |
| Market Cap | Share price multiplied by shares outstanding. | It describes company scale, not safety. | AUM |
| Price INR | Indicative USD price converted using available USD/INR data. | It aids context but is not an executable quote or full landed cost. | Price USD |
| Price USD | Instrument price in US dollars. | This is the native-price view before currency conversion. | Price INR |
| USD/INR | Number of Indian rupees per US dollar. | Its movement affects INR-equivalent value and returns. | Currency Exposure |
| US ETF / US Stock | US-listed basket fund / individual-company equity. | The UI badges them separately and shows different detail metrics. | ETF, Stock |

## Options

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| <a id="a3"></a>Ask | Lowest displayed price a seller is offering. | Difference from bid is the spread and a liquidity clue. | Bid, Spread |
| ATM — At the Money | Strike nearest the current spot price. | Fortress identifies the nearest available strike, which may not equal spot exactly. | Strike, Spot |
| Bid | Highest displayed price a buyer is offering. | It is not guaranteed execution and should be compared with ask. | Ask, Spread |
| Break-even | Underlying price where modelled expiry P&L equals zero. | It follows entered legs/premiums and model assumptions. | Payoff |
| Call / CE | Option giving its buyer the right, not obligation, to buy at strike under contract terms. | CE identifies calls in chain/Strategy Lab. | Put, Strike |
| Change in OI | Difference in outstanding contracts over the measured interval. | It describes positioning changes, not trader intent with certainty. | Open Interest |
| Delta | Approximate option-price sensitivity to a small underlying-price move. | It changes with market conditions and is not a fixed probability. | Gamma |
| Expiry | Date after which the option contract ends. | Chain, payoff, and comparison are specific to the selected expiry. | Holding Period |
| Gamma | Approximate rate at which delta changes as underlying price changes. | It shows curvature risk and can increase near expiry/ATM. | Delta |
| Implied Volatility / IV | Volatility level consistent with observed option prices under a model. | It reflects pricing expectations/conditions, not a guaranteed future range. | Premium, Vega |
| ITM / OTM | In/Out of the Money: whether immediate exercise has intrinsic value. | Moneyness organizes contracts; profitability also depends on premium. | ATM, Strike |
| Lot Size | Contract multiplier/quantity convention. | Payoff depends on quantity; verify provider/contract specifications. | Quantity |
| Maximum Loss / Profit | Theoretical worst/best expiry outcome under the entered structure. | It is separate from min/max points in Fortress’s displayed evaluation range. | Payoff, Unbounded |
| Moneyness | Relationship between strike and spot (ITM/ATM/OTM). | It makes the chain easier to interpret. | Strike, Spot |
| Open Interest / OI | Number of outstanding option contracts. | OI threshold filters the chain; OI is not a recommendation. | Volume, Put/Call OI |
| Payoff | Modelled profit/loss as underlying price changes, usually at expiry here. | Fortress’s table samples a displayed range; it is not the complete theoretical domain. | Break-even |
| Premium / LTP | Option price paid/received; LTP is last traded price. | Strategy results depend directly on entered premium, and LTP may be stale. | Bid, Ask |
| Put / PE | Option giving its buyer the right, not obligation, to sell at strike under contract terms. | PE identifies puts in chain/Strategy Lab. | Call, Strike |
| Put/Call OI | Put open interest divided by call open interest. | It is descriptive positioning context, not directional certainty. | Open Interest |
| Snapshot | Persisted observation of chain/provider state at a time. | Two successful snapshots are needed for What Changed. | Freshness |
| Spot | Current/reference underlying price supplied by the provider. | Moneyness and ATM selection depend on it. | Strike |
| Spread | Difference between ask and bid. | A wider spread can indicate higher trading friction/lower liquidity. | Bid, Ask |
| Strategy / Leg | Combination / one component of BUY or SELL call/put exposure. | Strategy Lab calculates the exact explicit legs entered. | Payoff |
| Strike | Contract’s specified exercise price. | It anchors intrinsic value and payoff shape. | Spot, Moneyness |
| Theta | Approximate sensitivity of option price to passage of time. | It is model-dependent and not a fixed daily charge. | Expiry, Premium |
| Unbounded | No finite theoretical limit in one payoff direction under the model. | Do not replace it with the largest sampled payoff point. | Maximum Profit/Loss |
| Vega | Approximate sensitivity of option price to implied-volatility changes. | It describes IV exposure, not direction. | IV |
| Volume | Contracts traded during the measured session/period. | It describes activity; it differs from outstanding OI. | Open Interest |

## Paper trading and portfolio records

| Term | Plain-English definition | Why it matters in Fortress | Related |
|---|---|---|---|
| <a id="e2"></a>Entry / Exit | Recorded opening / closing price or event for a simulated position. | Their difference, quantity, and assumptions drive realized P&L. | Return, P&L |
| Expectancy | Average expected result per observation based on recorded wins/losses. | It combines frequency and size but remains sample-dependent. | Win Rate |
| Holding Period | Time between entry and exit (or current time while open). | Outcomes from different horizons may not be comparable. | Entry, Exit |
| Notional / Exposure | Reference value represented by quantity × price (or contract convention). | It shows capital/risk scale in the simulation. | Quantity |
| Order | User-maintained record with type/status/broker fields. | Logging an order is not proof it was sent to or filled by a broker. | Executed |
| P&L — Profit and Loss | Monetary gain/loss after the simulation’s included assumptions. | Open P&L is unrealized; closed P&L is a historical observation. | Return |
| Paper Trade | Simulated position linked to an eligible recorded signal. | It changes saved simulation data but never commits real capital. | Open Position |
| Pick | A monitored idea recorded in Picks Tracker. | Its eventual label is evidence, not a retroactive prediction guarantee. | Outcome |
| Portfolio Return | Change in simulated portfolio value over a defined base/period. | Its meaning depends on exposure, cash, timing, and methodology. | Benchmark |
| Quantity | Number of shares/units/contracts in a record. | It scales notional and P&L. | Notional |
| Return | Percentage gain/loss relative to an entry/base value. | Compare like periods and distinguish realized from unrealized. | P&L |
| Turnover | Total trading activity relative to capital or as defined by the metric. | Higher turnover can imply more friction/cost, even in a simulation. | Exposure |
| Watchlist | Saved list of instruments to revisit. | Adding/removing is a stored preference, not a position or recommendation. | Portfolio |
