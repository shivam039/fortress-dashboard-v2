# PRODUCT4 — Paper Trade Lifecycle

Paper trading remains a user-confirmed simulation:

`Signal or Manual → Open Position → Reference Price/P&L → User Close → Closed History`

Open-position valuation is read-only and uses the backend’s authoritative entry,
quantity, and latest reference price. When market data is unavailable, the API
returns `null` for current price and unrealized P&L; the UI displays
“unavailable”, never a fabricated zero.

The paper-trade row preserves PRODUCT3 provenance (`source_type`,
`source_scan_id`, `oracle_version`, and the original `oracle_decision`) through
closing. Manual and legacy rows remain readable without inferred Oracle data.
Closing is an explicit user action with confirmation. The backend transitions
only an open row, so a repeated or concurrent close cannot create a second
close transition. Closed history shows entry, exit, realized P&L, timestamps,
and source.

PRODUCT4 does not call Oracle to decide whether to close, change Scanner or
Oracle semantics, auto-close positions, or place brokerage orders.
