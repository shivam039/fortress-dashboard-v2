# Oracle v1 outcome validation

Status: ORACLE3 measurement contract

Oracle outcomes measure what happened after an immutable Oracle v1 decision;
they do not tune or redefine the decision. The decision snapshot is the
existing append-only `signal_ledger` row, identified by `signal_id`, with
`oracle_version: oracle-v1`. Historical evaluation must use the decision-time
symbol, timestamp, price, decision, and snapshot—not a later score or feature.

## Outcome contract

The reference price is `signal_ledger.price_used`, falling back only to the
point-in-time snapshot `Price`. Future prices are the close of the 1st, 5th,
and 20th available trading sessions strictly after the signal date. Calendar
days and pre-decision bars do not count.

Each horizon is `MATURED`, `PENDING` when insufficient future sessions exist,
or `DATA_UNAVAILABLE` when the reference/future price is invalid or missing.
No prices are manufactured.

## Scorecard

The descriptive scorecard groups matured outcomes by decision and horizon and
reports sample count, mean return, median return, positive-return rate, and
exclusion count. Fewer than 20 matured observations is labeled
`INSUFFICIENT_SAMPLE`. The language is historical observation, never accuracy,
probability, significance, or a recommendation.

The pure implementation is in `engine/oracle_outcomes/service.py`; it does not
change Oracle v1 mapping, scanner scores, paper trading, or provider behavior.
Persistence/backfill and a production refresh job remain a follow-up once the
local outcome contract is reviewed. No production data or backfill was run.
