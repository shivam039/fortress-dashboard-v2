# FORTRESS-R1: historical score dataset, schema v1

## Purpose and data availability

Build an offline, reproducible SQLite dataset of archived Fortress stock scores
and future price-return labels. Run from the repository root; Python 3.9+ and
only its standard library are needed by the builder. There are no network calls,
provider imports, new dependencies, scoring changes, fitted weights, or UI.

This is **snapshot replay**, not historical rescoring. `Score` means the final
0–100 stock-scanner `apply_advanced_scoring` output, including existing regime,
quality-gate, and avoidance adjustments. It is not `ai_score`, raw conviction,
or an MF/REIT/US score. Category scores are the archived normalized outputs.
The builder never recalculates or renormalizes them on the research universe.

`engine/stock_scanner/logic.py` normalizes across a scan's universe and reads
current metadata upstream. `engine/utils/db.py::save_scan_results` retains
`raw_data`, but legacy scan rows do not establish source publication timestamps,
input vintages, complete scan configuration, or scoring revision. Neither a
scan timestamp nor a fiscal period end proves input availability. **Do not
certify those rows, backdate current metadata, or fabricate missing snapshots.**
The local legacy database was not used to publish a purported bias-free dataset.
No production historical dataset or predictive result is claimed in this story.

The implementation supplies the dataset format, validated builder, CLI, and
synthetic regression coverage. Real coverage is limited to dates for which the
input bundle described below can be assembled with defensible evidence. Dates
with membership but no eligible snapshot remain visible with null scores.

## Point-in-time contract

Choose and record one exchange/session calendar and one cutoff per session,
including its explicit UTC offset. For example, a research decision cutoff can
be `16:00:00+05:30`; it need not equal the exchange close. Include **all exchange
sessions**, even when no symbol has a price. Supply holidays and exceptional
sessions from the declared calendar source; the builder deliberately does not
infer a calendar from prices, weekdays, or today's exchange calendar.

For each run:

1. Archive the exact scored rows, full effective scoring configuration, code
   revision, and entire normalization universe, including failed-quality rows.
2. Archive every input dependency: OHLCV, benchmark/VIX history, financial
   filings and their original vintage, news, sector classifications, event
   context, and cross-sectional inputs. Keep these objects immutable.
3. Record each input object's **latest actual availability time** and latest
   observation time. For a batch these are maxima across all constituent data.
   Availability means published and accessible to the scorer, never merely the
   economic observation date. Corrected/restated data retain their later
   availability time. Store publication/ingestion evidence inside the archive.
4. Every input's `available_at` and `observed_through` must be at or before
   `scored_at`. That timestamp must belong to the run's local session date.
   Eligibility further requires `scored_at <= session cutoff`. Equality passes.
5. Do not include future observations in an input archive. A calendar of future
   earnings announced in the past may be known then; its *knowledge time*, not
   the future event date, is the observation timestamp for this purpose.

The builder validates timestamps and archive content hashes. It cannot prove
that a producer truthfully declared timestamps, included every dependency, or
used the stated revision/configuration. Source-vintage auditing remains the
producer's responsibility; never treat a successful import as certification.
When historical evidence is unavailable, omit the run rather than invent it.

Historical membership must be explicitly supplied per date and symbol, known
by that date's cutoff. Use an archived selection/listing history, including
subsequently delisted securities; do not take today's constituents backwards.
Membership determines output rows and is separate from each run's full scoring
universe. Use stable, exchange-qualified security identifiers consistently;
resolve ticker reuse, renames, and series changes in the source adapter.

For each member/date, select the latest eligible same-date snapshot by UTC
`scored_at`; ties use lexicographically greatest `run_id`. IDs must be stable
across rebuilds. No carry-forward or next-session reassignment occurs. An
ineligible after-cutoff run is retained in the hashed source bundle but not
selected. Inputs after its own scoring timestamp fail the entire build even
when that run would not be selected. Partial runs also fail: snapshots must
cover their complete declared normalization universe.

## Return convention

For horizon `h` in **5, 10, 20, 60 exchange trading sessions**:

```
forward_return(T, h) = unadjusted_close(T+h) / unadjusted_close(T) - 1
```

`T+h` is calendar position plus `h`, excluding T. Returns are decimal simple
returns (0.05 means 5%), with no rounding, compounding assumption, fees, slippage,
dividends, or reinvestment. They are unadjusted price returns, **not total
returns**. Splits, bonuses, rights issues, and other corporate actions can make
these labels economically misleading; audit these separately before research
use. Do not mix adjusted and unadjusted series, currencies, or security IDs.

This is a descriptive close-to-close label. A score known after T's close
cannot be executed at that close; these labels do not imply an executable
backtest. Designing next-open execution labels is a separate story.

A missing intermediate symbol price does not shift the target. A missing exact
endpoint leaves a null. No forward-fill, interpolation, zero imputation,
delisting payoff assumption, or dropping incomplete observations is performed.
Keep immature and delisted observations and inspect missingness before any
analysis. Provide at least 60 later sessions/prices when available. Observation
date filtering does not truncate the calendar or future prices used for labels.

## Immutable input bundle

Files are UTF-8. JSONL means one JSON object per line; blank lines are ignored.
Numbers must be finite JSON numbers (not numeric strings); absent score fields
and explicit JSON nulls remain missing. Duplicate keys, including JSON object
keys, fail rather than silently overwrite. Unknown scored-row fields are not
copied unless in the documented feature allowlist.

```
bundle/
  manifest.json
  sessions.jsonl
  membership.jsonl
  runs.jsonl
  snapshots.jsonl
  prices.jsonl
  inputs/<sha256>       # exact archived input bytes, no extension
```

`manifest.json` requires:

```json
{
  "schema_version": 1,
  "calendar": "YOUR_EXCHANGE_AND_CALENDAR_VERSION",
  "price_convention": "unadjusted_close",
  "sources": {
    "sessions": "immutable calendar export identifier and revision",
    "membership": "immutable historical membership identifier and revision",
    "prices": "immutable official closing-price export identifier and vintage"
  }
}
```

These are placeholders, not market data. Add source extraction methodology,
adapter revision, exchange timezone, coverage limitations, symbol mapping,
price currency, and dataset vintage as extra manifest fields. The entire
manifest is retained. Never include credentials in an input bundle.

| File | Required fields and meaning | Unique key |
| --- | --- | --- |
| `sessions.jsonl` | `date`: YYYY-MM-DD local session date; `cutoff`: offset-aware ISO timestamp on that local date | date |
| `membership.jsonl` | `date`, `symbol`, `available_at`: membership knowledge timestamp at/before cutoff | date, symbol |
| `runs.jsonl` | `run_id`, `date`, `scored_at`, `scoring_revision`, `scoring_config` object, `universe` nonempty symbol list, `inputs` nonempty provenance list | run_id |
| `snapshots.jsonl` | `run_id`, `symbol`, `raw_data`: original scored-row object | run_id, symbol |
| `prices.jsonl` | `date`, `symbol`, `close`: strictly positive finite unadjusted official close or null | date, symbol |

All dates must refer to supplied sessions. Rows may be in any order; outputs
are inserted in sorted order. Do not include non-trading dates as placeholder
sessions. Multiple markets require separate bundles with their own calendars.

Each `runs.inputs` entry requires `source` (immutable object identifier),
`sha256` (64 lowercase hex characters), `available_at`, and `observed_through`.
Write the object's exact bytes to `inputs/<sha256>`; shared objects are stored
once. The builder checks their SHA-256 hashes, streaming these archive files.
For example, use `hashlib.sha256(path.read_bytes()).hexdigest()` when producing
an archive. The JSONL tables are loaded into memory; partition large histories
into documented date/universe bundles if needed, preserving full run universes
and forward session coverage. Never recompute normalized scores after partitioning.

For current-format scored rows, copy these fields **directly** from `raw_data`:

| Input field | Output observation column |
| --- | --- |
| `Score` | `fortress_score` |
| `Technical_Score` | `technical_score` |
| `Fundamental_Score` | `fundamental_score` |
| `Sentiment_Score` | `sentiment_score` |
| `Context_Score` | `context_score` |
| `Market_Regime` | `market_regime` |
| `Sector` | `sector` |
| `Quality_Gate_Pass` | `quality_gate_pass` (boolean → SQLite 0/1) |
| `Quality_Gate_Failures` | `quality_gate_failures` (original pipe-delimited reasons) |

No truthiness fallback is used: Score=0 and gate=false are preserved. Unknown
components are not replaced with neutral defaults. Empty gate-failure text
is distinct from null. Missing individual gate outcomes are not inferred.
If a producer has an older field schema, it needs a reviewed, versioned adapter;
the builder does not guess aliases or substitute another type of score.

`features_json` stores available original values for this v1 allowlist:
`Price`, `RSI`, `RS_6M`, `RS_Composite`, `RS_Rank`, `RS_Score`,
`Avg_Value_20D_Cr`, `Market_Cap_Cr`, `Debt_To_Equity`, `Vol_Surge_Ratio`,
`Dist_52W_High_Pct`, `Extension_Pct`, `Is_Coiling`, `Technical_Raw`,
`Fundamental_Raw`, `Sentiment_Raw`, `Context_Raw`, `Sector_Rotation_Bonus`,
`Sector_RSI_Z`, `Sector_Conviction_Z`, `Regime_Multiplier`, `India_VIX`,
`Score_Pre_Regime`, `Black_Swan_Flag`, `Avoid_Flag`, `Liquidity_Flag`.
Snapshot `Price` is an input feature and may differ from the official label
close. Canonical scores, sector, regime and quality gates are not duplicated in
this JSON. Additional raw fields remain in the immutable source bundle.

## Output SQLite schema

| Table | Contents |
| --- | --- |
| `metadata` | key/value, values encoded as canonical JSON: schema version, methodology ID, input hashes, builder source hash, original manifest, inclusive bounds, horizons, return convention |
| `sessions` | date primary key, cutoff normalized to UTC |
| `runs` | selected run_id primary key and provenance_json containing the complete original run object, configuration, input provenance and normalization universe once per run |
| `prices` | date/symbol primary key, nullable close; full supplied series retained once, shared by all horizons |
| `observations` | date/symbol primary key, membership_available_at UTC, selected run_id nullable, status, five score columns, market_regime, sector, quality_gate_pass, quality_gate_failures, features_json |
| `labels` | date/symbol/horizon primary key, target_date nullable, forward_return nullable, status; foreign key to observations |

Each membership row in the requested range produces one observation and exactly
four label rows, even if its score is missing. Observation statuses: `ok` (a
Fortress score exists, not a quality verdict), `missing_score` (eligible snapshot
but no Score), `missing_snapshot` (no eligible same-date snapshot).

Label status precedence is `outside_calendar`, `missing_base_price`,
`missing_target_price`, `ok`. Outside-calendar labels have null target dates;
missing prices retain the exact target date. Returns are null except for `ok`.
All selected failed-quality rows are retained; filtering them is an explicit
later research decision.

The dataset does not duplicate archived raw input files or full raw scored rows.
Keep the immutable bundle alongside the SQLite artifact: hashes identify inputs
but cannot restore deleted files. Unselected runs remain auditable in that
bundle. Existing outputs are never overwritten. Validation precedes writing;
a temporary database is committed/closed before atomic publication, so a failed
build does not leave an output pretending to be complete.

## Regeneration and verification procedure

1. Check out the exact repository commit used for the build. Use a virtual
   environment (`python3 -m venv .venv`, then `source .venv/bin/activate`). No pip
   installs are needed for the builder itself.
2. Freeze the six bundle files and all content-addressed input archives. Record
   producer/adapter revisions and source-vintage evidence as above. Archive the
   original effective configuration; do not substitute today's defaults.
3. Run from the repository root, using actual paths and desired inclusive dates:

   ```bash
   python -m engine.research.historical_dataset \
     --bundle /path/to/immutable-bundle \
     --output /path/to/new-dataset.sqlite \
     --start 2025-01-02 --end 2025-12-31
   ```

   Omit both bounds to use the full calendar range. Only observations are
   filtered. Reversed bounds or a range containing no membership rows fail.
   An existing output fails; use a new filename for a rebuild. Invalid input
   exits nonzero with an error. Missing future prices are valid null labels.
4. Rebuild to another filename with identical bundle, bounds, builder, Python
   and SQLite versions. Compare SHA-256 digests of both databases. Byte identity
   is regression-tested in the same runtime. Across SQLite versions compare
   sorted table contents and metadata rather than requiring binary identity.
   No wall-clock build timestamp or absolute source path is injected.
5. Inspect coverage and integrity before research use:

   ```sql
   PRAGMA integrity_check;
   PRAGMA foreign_key_check;
   SELECT status, COUNT(*) FROM observations GROUP BY status;
   SELECT horizon, status, COUNT(*) FROM labels GROUP BY horizon, status;
   SELECT key, value FROM metadata ORDER BY key;
   ```

6. For a flat analysis table, pivot labels or join on `(date, symbol)`; do not
   silently inner-join away missing scores or missing future returns. Example:

   ```sql
   SELECT o.*, l.forward_return AS return_20d, l.status AS label_20d_status
   FROM observations AS o
   LEFT JOIN labels AS l
     ON l.date = o.date AND l.symbol = o.symbol AND l.horizon = 20;
   ```

Tests use explicitly synthetic inputs in temporary directories, not invented
historical trading results. With the repository development environment active:

```bash
python -m pytest tests/backend/test_historical_dataset.py \
  tests/backend/test_stock_scanner_scoring.py \
  tests/backend/test_scoring_equivalence_p2.py \
  tests/backend/test_conviction_regressions.py -q
python -m ruff check engine/research tests/backend/test_historical_dataset.py
```

Follow-ups outside R1: provider-specific point-in-time acquisition and legacy
provenance recovery, automated source-vintage auditing, corporate-action/total
return labels, delisting payoffs, and executable strategy evaluation. No
predictive-success claim follows from constructing this dataset.
