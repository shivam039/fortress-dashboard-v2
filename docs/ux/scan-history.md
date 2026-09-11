# FORTRESS-UX1: Section-Aware Scan History & Historical Scanner Views

## BEFORE

Scan History (`/history`) was one dropdown mixing every scan_type
(STOCK/MF/COMMODITY/OPTIONS) sorted only by timestamp, and opening a run
rendered the raw stored rows in a single generic `DataTable` — nothing like
the live Stock Screener's momentum/long-term/actionable structure. A user
had no way to see "just my stock scans" or recognize a historical run as
the same screener they use live.

## AFTER

`SCAN HISTORY -> SELECT SECTION -> THAT SECTION'S HISTORY -> OPEN RUN ->
READ-ONLY HISTORICAL VERSION OF THAT SCANNER`.

- A `.tabs` section selector (existing app pattern, reused verbatim — see
  `frontend/src/app/login/page.tsx`) lists only scan_types with real rows,
  plus **Stocks** always (the primary section, default on first visit).
  Selection persists to `localStorage` and to `?section=` in the URL
  (`resolveInitialSection`: URL > localStorage > Stocks).
- History rows are friendly cards: date • time, universe coverage ("4
  universes" for an E3 `AUTO_MULTI(...)` run), stocks analysed, a COMPLETE
  badge — not a raw table.
- Opening a **Stock** run renders `HistoricalStockScreener`: a Scan Summary
  card (coverage / analysed / candidates / status), then the exact same
  `ScannerResultsView` the live Stock Screener uses (metrics, Momentum
  Picks, Long-Term Picks, full results, Filtered Out), then raw JSON
  collapsed behind "Advanced details". A `🔒 Read-only` badge replaces any
  scan-triggering control; "← Back to Scan History" is the only navigation.
- Opening any other section's run renders `HistoricalGenericScan`: a
  smaller summary card + the raw rows behind a collapsed "Scan details"
  section — still section-labeled, still read-only.
- Only lightweight `{scan_id, timestamp, universe, scan_type, num_scanned}`
  rows are fetched when Scan History opens; the full payload for a run is
  fetched only when that run is opened (`historyApi.data(scanId)`).

## COMPONENTS REUSED

`ScannerResultsView` (new) was extracted from `screener/page.tsx`'s results
block — the live Stock Screener now renders it with `mode="live"`, and
`HistoricalStockScreener` renders it with `mode="historical"`. Same
`DataTable`/`MetricCard` primitives; same `Quality_Gate_Pass`/`Strategy`
grouping (`splitStockResults`, shared logic). This is the only place a
historical view could recompute a live value — it doesn't: rows are passed
through unchanged (`splitStockResults` never mutates a row; see
`tests/scan-history.test.mjs`'s object-identity assertion). Sector
Intelligence and the Conviction Heatmap are **not** reused — that data
comes from a separate live-only endpoint (`getSectorPulse`) never
persisted per scan; showing it for a historical run would mean recomputing
today's sector picture and mislabeling it historical, so it's omitted
entirely rather than faked.

## FILES CHANGED

- `frontend/src/lib/scan-history.ts` (new) — pure section/filter/URL/
  localStorage logic.
- `frontend/src/components/ScannerResultsView.tsx` (new) — extracted
  shared results presentation.
- `frontend/src/components/HistoricalStockScreener.tsx` (new).
- `frontend/src/components/HistoricalGenericScan.tsx` (new).
- `frontend/src/app/history/page.tsx` — rewritten, section-first.
- `frontend/src/app/screener/page.tsx` — results block replaced with
  `<ScannerResultsView results={results} mode="live" />` (no behavior
  change).
- `frontend/src/lib/api.ts` — `ScanHistoryEntry` gained optional
  `num_scanned`.
- `engine/utils/db.py` — `fetch_scan_history_list()` adds one additive,
  cheap `COUNT(*)` subquery column (`num_scanned`); no other caller
  affected.
- `tests/backend/test_api.py` — one new assertion on `num_scanned`.

## TESTS

- `frontend/tests/scan-history.test.mjs` (new, 10 tests via
  `npm run test:ux1`): section availability/filtering, per-section
  chronology, initial-section resolution (URL/localStorage/default),
  localStorage round-trip, universe-coverage labeling, historical
  score/price preserved untouched (object-identity check), no live
  "Run Scan" control and raw JSON only behind "Advanced details" (static
  source checks — this repo has no component-render test harness, so
  these mirror the existing `scan.test.mjs` convention), and the detail
  payload is fetched only from the open-run handler, never on initial load.
- Existing `npm run test:scan` (14) and `test:u2` (16) still green — the
  live screener's behavior is unchanged.
- `npm run lint`, `npx tsc --noEmit`, `npm run build` all clean (17 routes
  prerendered, including `/history` and `/screener`).
- Backend: full suite `522 passed` (only `fetch_scan_history_list` and one
  test assertion touched).

## LIMITATIONS

- **Mutual Funds / Commodities / Options** use `HistoricalGenericScan`,
  not a dedicated MF/Options-shaped reconstruction: the live MF Lab and
  Options pages (`mf_lab`, `options_algo`) don't call `register_scan()` at
  all today, so any `MF`/`OPTIONS` rows in `scan_history_details` are
  legacy-cron artifacts (`cron_mf_audit.py`, the old Streamlit
  `options_algo/ui.py`), not something the live pages currently produce or
  have a "live scanner presentation" to mirror. Rebuilding a faithful
  MF-specific historical view would mean reverse-engineering a
  presentation for a scanner the app doesn't actively run — out of this
  story's scope per its own P2/documentation-limitation allowance. If MF
  scan persistence is wired into the live `mf_lab` flow later, a
  dedicated `HistoricalMFScan` following the same `ScannerResultsView`
  pattern is the natural next step.
- **"All Activity" mixed view** was not added — the story marks it
  optional and explicitly deprioritized ("do not spend substantial
  implementation effort"); the section-first flow fully supersedes the old
  mixed dropdown's only real use.
- The history list shows "stocks analysed" but not an "opportunities"
  count per row (Part 5's example includes both) — computing candidate
  counts for every row would mean parsing every run's stored JSON in the
  lightweight list query, which conflicts with Part 19's "don't fetch
  every payload" performance goal. Candidate count is shown once a run is
  opened.

## SCREEN FLOW

```
Scan History → Stocks → 11 Sep 2026 • 9:15 PM → Historical Stock Screener
Scan History → Mutual Funds → <run> → Historical Mutual Funds Scan (generic view)
```
