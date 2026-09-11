# FORTRESS-E2: Automated Paper Portfolio

Automates T2 paper trading from real T1 signals so prospective evidence
accumulates without manual stock selection. Orchestrates T1/T2/E1 — none of
them are redesigned. No real broker execution exists anywhere in this
module.

## Pipeline

```
FULL UNIVERSE SCAN -> E1 records every scored ticker -> T1 records signals
-> E2 (this story): process_new_signals() -> T2 open_position_from_signal()
-> ... next trading session(s) ... -> E2: manage_open_positions()
-> T2 simulate_exit() -> performance accumulates
```

## Policy (`engine/paper_trading/policy_engine.PaperPolicy`)

One explicit, versioned dataclass (`policy_version = "e2-policy-v1"`).
Position sizing, exposure, holding period, and stop/target rules are T2's
own `PaperTradingConfig`, reused unchanged — E2 does not reinvent them.

| Field | Source | Value |
| --- | --- | --- |
| minimum qualifying signal | Fortress's own `Quality_Gate_Pass` (in every signal's `feature_snapshot`) | must be true |
| max simultaneous positions | T2 `PaperTradingConfig.max_simultaneous_positions` | 10 (T2 default) |
| max position notional | T2 `PaperTradingConfig.max_position_notional` | 100,000 (T2 default) |
| max total exposure | T2 `PaperTradingConfig.max_total_exposure` | 500,000 (T2 default) |
| duplicate-symbol behavior | E2 `allow_duplicate_symbol` | `False` — skip if a symbol already has an open position |
| entry-price convention | E2 `_next_session_open()` | next session's real Open (see below) |
| stop/target convention | T2 `simulate_exit()`, unchanged | first-touch: stop before target within a bar |
| max holding period | T2 `PaperTradingConfig.max_holding_period_days` | 30 (T2 default) |
| transaction-cost assumption | E2 `PaperPolicy.config.cost_bps` | **10 bps round-trip** — a conservative documented default (T2's own dataclass default of 0.0 means "uncosted," appropriate for isolated exit-logic tests, not for prospective evidence) |
| policy version | `PaperPolicy.policy_version` | `"e2-policy-v1"` |

No value here was tuned from any observed outcome.

## Entry convention — no look-ahead

A signal's `suggested_entry`/`price_used` (the EOD scan price) is **not**
used as the executable entry price. E2 looks up the real Open of the first
trading session strictly after the signal's date, using the fetched OHLCV
series' own trading-day index (same technique E1's maturation already
uses — no invented calendar). If that session hasn't happened yet, the
signal is recorded `PENDING_ENTRY` and re-checked on the next run —
**never** opened early. This is why automated entry is a daily job, not a
step run synchronously inside the scan request: the next session's open
cannot exist yet at scan time.

## Automatic entry (`process_new_signals`)

1. Every signal_ledger row with no `paper_policy_decisions` row yet
   (`fetch_undecided_signals`, id-ascending — deterministic), plus any
   `PENDING_ENTRY` signal from a prior run.
2. **INVALID_SIGNAL** if: no valid entry price, no matching E1 research
   observation for `(scan_id, symbol)` (E1 already skips recording
   observations for a circuit-broken scan — this is the existing, free
   signal reused to detect an invalid source scan), or `Quality_Gate_Pass`
   is not true.
3. **REJECTED_DUPLICATE_SYMBOL** if an open position already exists for
   the symbol and `allow_duplicate_symbol` is false.
4. **PENDING_ENTRY** if the next session's open isn't available yet.
5. Otherwise T2's own `open_position_from_signal()` decides: **OPENED**,
   or **REJECTED_MAX_POSITIONS** / **REJECTED_EXPOSURE** (T2's own
   rejection reasons, mapped to these labels) / **REJECTED_POLICY**
   (persistence failure or any other T2 rejection).

Every signal gets exactly one decision row — nothing is silently dropped.

## Automatic position management (`manage_open_positions`)

For every open paper trade: fetch real OHLCV, build the price path since
entry, hand it to T2's unchanged `simulate_exit()` (first-touch stop/
target, then max-holding-period time exit, transaction costs per the
policy's `cost_bps`), and close via T2's `close_paper_trade()` if resolved.

## Idempotency

- **Entry**: `paper_policy_decisions` is keyed on `signal_id` (upsert) — a
  rerun finds the signal already decided and skips it entirely.
- **Management**: `close_paper_trade` only ever acts on trades a fresh
  `fetch_paper_trades(status="open")` still returns; once closed, a trade
  never appears there again, so a rerun cannot reclose it or double-apply
  costs.

## Audit trail

`paper_trade.signal_id` → `signal_ledger` row → `(scan_id, symbol)` → the
matching `research_observations` row → `scoring_version`. Every
non-opened signal has a `paper_policy_decisions` row with its
`policy_version` and a human-readable rejection reason.

## Daily operation

```bash
PYTHONPATH=.:engine .venv/bin/python -m paper_trading.policy_engine run
```

Idempotent — manages existing positions first (freeing exposure/slots),
then processes newly eligible signals. Output:

```json
{"policy_version": "e2-policy-v1", "open_before": 7, "closed_today": 2,
 "new_eligible_signals": 14, "opened": 5, "rejected_exposure": 3,
 "rejected_max_positions": 4, "rejected_duplicate_symbol": 2,
 "rejected_policy": 0, "invalid_signal": 0, "pending_entry": 0, "open_after": 10}
```

## Status

```bash
PYTHONPATH=.:engine .venv/bin/python -m paper_trading.policy_engine status
```

Reports open/closed position counts, T2's own `compute_metrics()` (win
rate, expectancy, max drawdown, exposure, P&L — never fabricated; an empty
trade set reports zeros/None, not invented numbers), policy version, and
signals considered/accepted/rejected by decision type.

## Files changed

- `engine/utils/db.py` — `paper_policy_decisions` table + `upsert_policy_decision`/
  `fetch_undecided_signals`/`fetch_policy_decisions`.
- `engine/paper_trading/policy_engine.py` (new) — policy + orchestration + CLI.
- `tests/backend/test_paper_policy_engine.py` (new) — 16 tests.

`engine/paper_trading/logic.py` (T2) and `engine/routers/paper_trading.py`
(the manual paper-trading API from FORTRESS-V4) are unchanged — the manual
"open from a signal" API path remains available alongside this automated
one.
