# PRODUCT3 Discovery

Status: `PRODUCT3_SELECTED`

## Shortlist

1. **Scanner → Oracle → paper-trade provenance** — Scanner/Paper Trading.
   Highest user value because it connects existing workflows without changing
   financial semantics. Medium risk; expected files are scanner/paper-trade
   routers and frontend detail components; tests cover provenance identity.
2. **Scan History evidence context** — Scan History. High value and low risk;
   expose existing signal/oracle metadata in history. Tests cover read-only
   rendering and missing metadata.
3. **Oracle decision history UX** — Oracle. Medium value, medium risk; requires
   a product choice about grouping and pagination.
4. **Watchlist bootstrap reliability** — Watchlist. Useful but lower priority;
   existing QA work already covers failure surfacing.

## Selection

`PRODUCT3_SELECTED`: Scanner → Oracle → paper-trade provenance.

This is the clearest missing connection among already-supported surfaces. It
should link a paper-trade record to its originating signal and immutable
Oracle-v1 decision, using existing IDs only. It must not alter scoring,
decision mapping, or paper-trading semantics. Expected scope is one focused
PR with backend response fields, read-only UI context, and contract tests.

Oracle tuning, Oracle v2, calibration, and confidence changes are explicitly
rejected because EVIDENCE1 remains `NOT_ENOUGH_EVIDENCE`.
