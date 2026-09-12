# Oracle Decision MVP

Status: ORACLE1 product contract  
Baseline inspected: `8900ef7ecd234510c2be3715f09ef43d17cf8bb6`  
Scope: product design and codebase research only

This document is the implementation contract for ORACLE2. It intentionally
does not add an endpoint, UI, table, scoring formula, trade path, provider, or
deployment change.

## Product decision

### User story

As a Fortress user, I can select a current Indian-equity scanner candidate and
see a reproducible interpretation of the evidence Fortress already calculated,
including its limitations and freshness, before I optionally prepare a paper
trade.

### Primary question

**Given this persisted scanner candidate and its point-in-time evidence, what
does Fortress currently indicate about this stock?**

Oracle is decision support. It is not a portfolio manager, adviser, price
predictor, chatbot, or autonomous trader.

### Asset scope

MVP supports Indian equities represented by the existing stock scanner and
`signal_ledger`. Mutual funds, REIT/InvIT, US equities, commodities, options,
and multi-asset decisions are out of scope.

## Existing evidence inventory

The scanner's `check_institutional_fortress` output and the immutable
`signal_ledger` provide the following evidence. Oracle must display or
interpret these fields; it must not recompute them.

| Evidence | Source / shape | Meaning and availability |
| --- | --- | --- |
| `Score` | scanner row; numeric conviction score, normally 0–100 | Existing aggregate score; persisted as `signal_ledger.score` |
| component scores | scanner `sub_scores`; JSON object | Technical, fundamental, sentiment, and context components where present; persisted as `component_scores` |
| `Market_Regime`, `Regime` | scanner row; text | Existing market-regime context; persisted as `market_regime` |
| `RS_Score` | scanner row; numeric | Relative strength versus Nifty; retained in `feature_snapshot` |
| `RSI`, EMA/trend fields | scanner row; numeric/bool | Existing technical context; retained in `feature_snapshot` when produced |
| `Ret_7D`, `Ret_30D`, `Ret_60D`, `Ret_90D`, `Velocity` | scanner row; numeric | Observed historical price changes and velocity; retained in `feature_snapshot` |
| volatility/liquidity/quality flags | scanner row; fields such as `Black_Swan_Flag`, `Quality_Gate_Failures`, volume and liquidity metrics | Cautions, not probability estimates; retained in `feature_snapshot` |
| `Price`, `Stop_Loss`, `Target_10D`, `Position_Qty` | scanner row; numeric | Existing setup/risk fields. Oracle may show them as source evidence, but must not change their calculation or imply a guarantee |
| `Verdict`, `Strategy`, `Explanation` | scanner / ledger text | Existing descriptive semantics; do not replace with competing definitions |
| `symbol`, `sector`, `universe`, `scan_id`, `scan_version` | scan context | Identity and provenance |
| `generated_at`, `data_timestamp`, `data_source` | scan/ledger metadata | Decision and underlying-data freshness |

The ledger stores `feature_snapshot` as a point-in-time record and is append
only. Re-scanning a symbol creates a new row; it does not rewrite prior
evidence. This makes `signal_id` the preferred Oracle input and provenance key.

Historical forward-return evidence is a separate R2 concept. It is available
only when the research-evidence endpoint reports a real R2 result and adequate
sample size. Fixture evidence is never an Oracle input.

## Existing recommendation semantics

The repository contains several descriptive vocabularies, including scanner
`Verdict`/`Strategy`, plain-English conviction `Decision` text for MF and
commodities, and paper-trading decisions such as `OPENED`, `PENDING_ENTRY`,
and `REJECTED_*`. None is a universal equity Oracle contract.

Therefore Oracle must not invent `BUY`/`SELL` semantics or silently reinterpret
paper-policy statuses. The MVP vocabulary below is deliberately weaker and
descriptive.

### Oracle vocabulary

| Label | Meaning | Required evidence | Does not mean |
| --- | --- | --- | --- |
| `POSITIVE` | Existing scanner evidence is directionally supportive, with no blocking data-quality or risk condition | Valid persisted signal, usable score/context, no blocking freshness/quality failure | A buy instruction, expected return, or profitable outcome |
| `NEUTRAL` | Evidence is mixed, insufficiently differentiated, or lacks a strong directional case | Valid signal but conflicting/ordinary evidence | A hold recommendation or a forecast |
| `NEGATIVE` | Existing evidence is directionally unfavorable or a blocking risk/quality condition dominates | Valid signal with explicit negative evidence or failed quality/risk condition | A sell instruction or claim that price will fall |
| `UNAVAILABLE` | A decision cannot be safely formed | Missing signal, invalid required fields, stale required data, or partial data below the contract threshold | Neutrality, zero score, or a guessed decision |

The mapping from existing fields to these labels is an ORACLE2 implementation
policy and must be expressed as a small, reviewed rule table. It must not
alter scanner score thresholds, paper-trading thresholds, or persisted scores.
If the available fields cannot support a deterministic mapping, return
`UNAVAILABLE` rather than guess.

## Confidence and explanation

MVP has **no numeric probability** and no claim such as “82% chance of
profit.” A score is not a probability.

Expose confidence only as evidence completeness:

- `HIGH`: required signal fields and freshness are valid; supporting evidence
  is internally consistent.
- `MEDIUM`: the signal is valid but one non-critical supporting field is
  missing or partial.
- `LOW`: the signal is usable only with material limitations; this must not
  override `UNAVAILABLE` when required data is invalid or stale.

The response must contain concise, source-backed lists:

- `reasons`: existing positive/supporting fields and their values.
- `cautions`: missing, stale, risk, quality, or conflicting fields.
- `data_as_of`: underlying data timestamp when available.
- `generated_at`: signal/decision context timestamp.
- `source_context`: `signal_id`, `scan_id`, `scan_version`, `universe`, and
  `data_source`.

No free-form LLM explanation is required. Every displayed reason must map to
an existing field or an explicit data-quality condition.

## Freshness and failure behavior

The decision must preserve the distinction between fresh, stale, partial, and
missing evidence:

| State | Behavior |
| --- | --- |
| Fresh, complete | Return the deterministic label and evidence |
| Fresh, partial | Return a label only if required fields remain valid; mark confidence `MEDIUM`/`LOW` and list the missing fields |
| Stale required data | Return `UNAVAILABLE`; show the timestamps and require a new scan |
| Missing/invalid signal or required fields | Return `UNAVAILABLE` with a safe reason; never substitute zero or current ad-hoc data |
| Historical R2 evidence absent/insufficient | Omit the metric or return it as unavailable; never use fixture data |

The precise staleness window is the one human decision left below. It must be
centralized and visible in the response, not hidden in UI code.

## Scanner → Oracle contract

Preferred input is a persisted `signal_id`. This lets Oracle consume the exact
scanner snapshot without rerunning the full scan. A future convenience input
may accept `symbol + scan_id`, but it must resolve to one immutable ledger row
and must not silently choose an unrelated latest row.

Minimum resolved input:

```json
{ "signal_id": 123 }
```

## Oracle API contract

Proposed read/evaluate endpoint:

`POST /api/oracle-decision`

Request:

```json
{ "signal_id": 123 }
```

Successful response:

```json
{
  "signal_id": 123,
  "symbol": "RELIANCE.NS",
  "decision": "POSITIVE",
  "confidence": "HIGH",
  "score": 74,
  "reasons": [
    { "key": "score", "label": "Fortress score", "value": 74 }
  ],
  "cautions": [],
  "data_as_of": "2026-09-12T10:00:00Z",
  "generated_at": "2026-09-12T10:01:00Z",
  "source_context": {
    "scan_id": 456,
    "scan_version": "...",
    "universe": "Nifty 50",
    "data_source": "..."
  },
  "paper_trade": {
    "available": true,
    "signal_id": 123
  }
}
```

`UNAVAILABLE` is a successful, explicit decision state when the signal exists
but cannot safely support interpretation. Missing `signal_id` is a client
error; an unknown signal is not found. The endpoint must not place a trade or
call an external provider.

## UI contract

Use a scanner-result drawer or modal, not a new navigation area. The scanner
already owns candidate context and the existing frontend uses focused cards and
async status/error states. The smallest UI is:

1. Add an `Oracle Decision` action to a persisted scanner result.
2. Show symbol, decision badge, score, confidence, reasons, cautions, and
   timestamps/source context.
3. Show `UNAVAILABLE` and a retry/rescan path without fabricating a result.
4. Do not redesign the screener or add a dashboard-wide Oracle page in MVP.

## Paper Trading and open positions

Existing Paper Trading accepts only `{ "signal_id": number }`. It resolves the
real ledger row, derives entry/stop/target through the existing deterministic
T2 logic, applies exposure/position limits, and persists a paper position. The
Oracle action must therefore pass the original `signal_id` only; it must not
send or override prices, quantity, side, stop, or target.

“Paper Trade” means: open the existing confirmation/order flow prefilled from
the persisted signal, then require the user to confirm. It never auto-submits.

If an open paper position already exists for the symbol, show `OPEN POSITION
EXISTS`, link to the existing open-position view, and do not silently create a
second position. The existing T2 rejection/limit behavior remains the final
authority.

Open-position records currently link to the originating `signal_id`; the
signal ledger contains the decision evidence snapshot. ORACLE2 may expose this
provenance read-only. It must not alter trade semantics or add duplicate
positions.

## Persistence and future outcomes

Recommended MVP: compute on demand from the immutable `signal_ledger` row and
do not create an Oracle table. This minimizes schema complexity while retaining
auditability through `signal_id`, `scan_id`, `generated_at`, and
`feature_snapshot`.

If historical comparison becomes necessary, ORACLE2+ can add an append-only
decision snapshot keyed by `signal_id` and decision timestamp. It should record
the contract version, label, evidence keys, and freshness state—not overwrite
the original signal.

Future outcome tracking can evaluate, without claiming predictive accuracy:

- price return after 1, 5, and 20 trading days;
- benchmark-relative return over the same windows;
- paper-trade outcome where a user actually confirmed a trade;
- label-specific coverage, hit rate, and calibration after sufficient samples.

These are validation measurements, not current Oracle inputs or promises.

## Recommended MVP and alternatives

### Recommended: deterministic scanner interpretation

One PR, one read-only backend contract, one scanner drawer, and a handoff to
the existing paper-trade confirmation path. Smallest value/risk balance;
reproducible and explainable.

### Alternative A: persisted decision snapshots

Adds an Oracle snapshot table and versioned history immediately. It improves
audit/outcome analysis but increases schema, migration, and consistency work.

### Alternative B: historical-evidence-enhanced decision

Adds real R2 evidence when available. It may improve context, but must handle
insufficient samples/staleness and is not required for the first contract.

The recommendation is the deterministic interpretation MVP; A and B can follow
only after the base contract is exercised.

## ORACLE2 implementation plan

One PR is feasible:

1. Add a pure backend decision service that reads one ledger snapshot and
   applies the reviewed rule table; no scanner changes.
2. Add `POST /api/oracle-decision` with authentication, validation, freshness,
   redaction, and explicit unavailable states.
3. Add focused backend tests for each label, missing/partial/stale data,
   provenance, and no-trade behavior.
4. Add scanner action/drawer, API typing, loading/error/retry states, and
   frontend tests.
5. Pass the original `signal_id` to the existing user-confirmed paper-trade
   flow; test duplicate/open-position behavior.
6. Run existing scanner, paper-trading, frontend, lint, typecheck, and build
   suites. No deployment.

Expected files (subject to implementation discovery):

- `engine/oracle_decision/` or a small pure service module
- `engine/routers/oracle_decision.py`
- `engine/main.py` router registration
- `tests/backend/test_oracle_decision.py`
- `frontend/src/lib/api.ts`
- `frontend/src/app/screener/...` or a focused component
- frontend Oracle tests

Estimated complexity: **MEDIUM**.

## Human product decisions

### Decision 1 — stale-data window

- Option A: 1 trading day for the underlying market data (recommended).
- Option B: 5 calendar days.

Recommendation: Option A, because Oracle describes a current scanner snapshot
and stale evidence should fail closed.

### Decision 2 — decision interaction

- Option A: drawer/modal inside the scanner with a user-confirmed Paper Trade
  handoff (recommended).
- Option B: dedicated Oracle page.

Recommendation: Option A, because it preserves candidate context and avoids
navigation redesign.

No other product decision is required to begin ORACLE2. The exact rule-table
thresholds should be reviewed as implementation acceptance criteria, but they
must be derived from existing scanner semantics rather than invented as a new
score.

## Safety boundaries

- Auto trade: **NO**
- Live brokerage: **NO**
- Fake probability: **NO**
- Scoring changes: **NO**
- LLM required: **NO**
- External LLM/provider calls: **NO**
- Production/deployment changes: **NO**

## Future scope

- MF support: deferred; existing MF conviction is a different asset contract.
- REIT/InvIT support: deferred.
- US support: deferred.
- Qwengate/DeepSeek/Claude/other LLMs: deferred to AGENT5A-QWEN or a separate
  experiment.

## ORACLE1 result

ORACLE1 is complete when this document is reviewed as the canonical contract.
It contains no application implementation and introduces no production impact.
