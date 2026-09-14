# Column tooltip audit

Audit date: 2026-09-14. Scope: every table declared in `frontend/src`.
`DataTable` resolves both explicit and API-discovered columns through the
canonical metadata registry; an honest contextual fallback covers provider
fields that are not known until runtime. Blank action columns are labelled for
assistive technology and intentionally have no tooltip.

| Table | Columns inventoried | Meaning | Tooltip | Glossary | Format | Status |
|---|---|---|---|---|---|---|
| Stock Screener / results | Symbol, Company, Price, Score, Strategy, Velocity, Target 10D, Stop Loss, Position Qty, plus returned analysis fields | Yes | Yes | Technical terms | In tooltip where canonical | PASS |
| Scan History / replay | API result columns, including Symbol, Fortress Score and quality gates | Yes | Yes | Technical terms | In tooltip where canonical | PASS |
| Dashboard orders | Symbol, Order Type, Quantity, Status, Broker Name, Created At | Yes | Yes | Relevant terms | Contextual | PASS |
| Orders and Picks | All API-returned record columns | Yes | Yes | Relevant terms | Contextual | PASS |
| Paper signals | Symbol, Score, Regime, Sector, Entry, Stop, Target | Yes | Yes | Yes | Score/currency | PASS |
| Open paper positions | Symbol, Entry, Current, P&L, Return, Stop, Target, Holding, Status | Yes | Yes | Yes | Currency/%/days | PASS |
| Closed paper trades | Symbol, Source, Entry, Exit, Realized P&L, Opened, Closed | Yes | Yes | Yes | Currency/date-time | PASS |
| Mutual Fund Lab | Scheme, Category, Sub Category, Conviction Score/Label, Confidence, Data Quality, NAV, 1Y/3Y/5Y Return, Sharpe, Sortino, Alpha, Volatility, Downside Deviation | Yes | Yes | Yes | ₹/%/ratio/status | PASS |
| US Investing | Symbol, Name, Sector, Price USD/INR, 1M/1Y Return, P/E, Score, Confidence, Flags | Yes | Yes | Yes | USD/₹/%/ratio | PASS |
| REITs / InvITs | Symbol, Name, Type, Price, Yield, 1Y/3Y distributions, 1M/1Y Return, Volatility, Score, Signal, Confidence, Quality | Yes | Yes | Yes | ₹/%/score | PASS |
| Options chain | Strike, Type, Moneyness, LTP, OI, Change OI, Volume, IV, Bid, Ask | Yes | Yes | Yes | ₹/contracts/% | PASS |
| Options snapshots | Captured At, Provider, Spot, Freshness, Snapshot ID | Yes | Yes | Yes | date-time/₹/status | PASS |
| Options payoff / strategy | Underlying, Expiry P&L and returned strategy columns | Yes | Yes | Relevant terms | ₹ | PASS |
| Commodities | API-returned columns and comparison Metric / commodity headings | Yes | Yes | Relevant terms | Contextual | PASS |
| Profile / broker connections | Broker, Client ID, Status, Action | Yes | Yes | Relevant terms | Contextual | PASS |

## Verification rule

New shared-table fields automatically receive a readable label and explanation.
Authors should add a canonical entry whenever a new financial field has stable
units or interpretation, rather than accepting the runtime fallback permanently.
