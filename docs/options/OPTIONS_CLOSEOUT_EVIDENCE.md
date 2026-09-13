# Options closeout evidence

This record describes what is proven by repository tests and what still
requires a live deployment observation. It is intentionally not a claim that
synthetic fixtures represent production market data.

## Proven in repository checks

- Canonical provider contracts reject malformed rows and expose response-level
  capability states and provider diagnostics.
- Snapshot writes are idempotent; history reports `INSUFFICIENT_HISTORY` until
  two successful observations exist, and comparison reports spot/provider and
  contract added/removed/changed counts.
- The payoff engine is pure and read-only. Its tests cover long/short calls and
  puts, vertical spreads, straddles, strangles, breakevens, and unbounded
  theoretical tails separately from grid extrema.
- Strategy Lab is reachable at `/options` and uses the same backend payoff
  endpoint for explicit multi-leg presets and user-edited legs. It does not
  place orders.
- Screener and instrument detail surfaces link into `/options?symbol=...`.

The focused backend command is:

```text
python -m pytest tests/backend/test_options_*.py -q
```

## Truthful runtime interpretation

The Options UI displays the provider, freshness, response capabilities, and
diagnostics returned by the selected provider. `UNAVAILABLE` is preserved as
unavailable; it is never converted into a supported capability or a numeric
zero. Live-provider availability and latency must be verified by the deploy
pipeline or an operator with access to the production environment.

## Legacy Strategy Scanner disposition

The legacy scanner remains descriptive and explicitly labelled as such. It is
not a recommendation or risk model. The read-only Strategy Lab is the intended
surface for explicit payoff analysis. The separate P0 scanner backtest wrapper
is retained only for existing history-screen call sites and now anchors its
forward-return baseline to the scan timestamp.

## Scope boundary

This closeout does not modify DATA2/Bhav Copy backfill jobs, production
schedulers, broker execution, Oracle migration code, or Qwen integration.
