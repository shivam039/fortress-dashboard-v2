# PRODUCT3: Scanner → Oracle → Paper Trade Provenance

Paper trades opened from a persisted signal now retain a compact, immutable
provenance snapshot:

- `source_type=ORACLE_SIGNAL`
- originating `signal_id`
- `source_scan_id` when available
- `oracle_version=oracle-v1`
- original `oracle_decision` (including truthful `UNAVAILABLE` when the
  existing signal lacks enough context for an Oracle interpretation)

The signal is looked up server-side by ID; frontend-supplied symbol, score,
decision, or pricing fields are not trusted. Existing paper-trade creation and
user confirmation semantics are unchanged. Existing rows remain readable,
and nullable/additive fields do not fabricate provenance for historical data.

Open-position valuation already joins through `signal_id`; the UI now displays
the source and original Oracle context in the position list/detail view. Oracle
market outcomes and simulated paper-trade outcomes remain separate metrics.

No scanner scoring, Oracle-v1 mapping, confidence, sizing, stop/target logic,
brokerage behavior, or automated trade behavior changed.
