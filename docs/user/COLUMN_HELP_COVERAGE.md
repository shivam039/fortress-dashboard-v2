# Contextual help coverage

Audit baseline: `f14963f3a6dc0f5e08dc3d5577e9c31f0238dfe0`.

The shared `DataTable` resolves headings through the canonical frontend help
registry. Explicit `helpKey` values remain available when a table uses a
context-specific meaning. Sorting and help are separate buttons.

| Surface | Representative columns audited | Help-covered technical columns | Status |
|---|---|---|---|
| Stock Screener / historical stock results | Score, RSI, ADX, ATR, Price, Signal | Score, RSI, ADX, ATR, Price, Signal | PASS when present in provider rows |
| Scan History generic results | dynamic provider schema | known canonical headings | PARTIAL — unknown provider fields remain intentionally unmatched |
| Options chain / payoff | Strike, Moneyness, LTP, OI, ChangeOI, Volume, IV, Bid, Ask, Underlying, Expiry P/L | all listed columns except Type | PASS |
| Mutual Fund Lab | NAV, AUM, Expense Ratio, Sharpe, Sortino, Alpha, Beta, Return, Drawdown, Score | all listed columns | PASS when present |
| Commodity shared table | Score, Volatility, Price, Confidence | all listed columns | PASS when present |
| Dashboard / Orders / Profile | Status, Price, Return plus administrative fields | technical fields; self-evident identity/action fields excluded | PASS |
| Picks Tracker | Hit Rate, Avg P&L, Score, Return, Status | all listed metrics | PASS when present |

## Known gaps

Custom HTML tables in Paper Trading, REITs & InvITs, and US Investing predate
the shared table and do not yet consume the registry. Their surrounding copy,
units, and existing contextual explanations remain available, but universal
per-header coverage is **not complete**. Dynamic backend/provider columns which
do not match a canonical term deliberately render without guessed help rather
than receiving a misleading definition.

This report therefore records the epic as **PARTIAL**, not universal coverage.
