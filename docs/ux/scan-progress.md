# FORTRESS-U1 — stock scan experience

The stock screener now keeps an observable lifecycle and its last response
outside the page component. This uses the existing synchronous `/api/scan`
contract. No backend, scoring, weight, or provider behavior changes.

## Visible states

- Universe loading: scan disabled until available; readable failure and manual
  retry if loading fails.
- Running: request in flight, selected universe, elapsed request wait time, and
  explicit stage `awaiting scan response`. Previous result tables remain usable.
- Completed: response received, row count, universe, and browser receipt timestamp.
  Zero rows is a terminal state, not the initial empty screen.
- Partial: preserve `circuit_breaker_tripped`, `summary`, `scanned`, and `failed`
  from the backend envelope, even when zero rows are returned.
- Failure: HTTP client rejection is shown persistently, preserving previous data.
- Unknown outcome: connection loss, timeout, malformed response, or server error
  may leave server work in progress. Link to Scan History before a manual retry.
  Going offline does not imply cancellation; coming online never resubmits.

The endpoint has no live progress, job status, server timestamp, or cancellation
API. The UI does not invent percentages, ticker counts, internal stage changes,
server liveness, or a confirmed stop. Normal array responses mean processing
returned, not guaranteed complete market-data coverage. Receipt time is clearly
identified as browser time, not market-data freshness. Accurate market-data,
metadata, indicator, scoring, and persistence stages require a future backend
job/status contract. Cancellation is deliberately omitted because aborting HTTP
would not stop server work.

## Navigation and refresh

An external store scoped to the authenticated username retains a pending request
through same-document navigation. `useSyncExternalStore` subscriptions detach
on unmount; reentering the screener reuses the request and results. Its timer is
isolated in a small status child rather than rerendering all tables every second.
There are no polling loops or automatic scan retries. Rapid duplicate starts are
rejected by the store, independently of the disabled button.

Per-user sessionStorage retains last results and a running marker within this
browser tab. Reloading restores results and changes an interrupted running marker
to unknown, never to completed or a resumed request. Other tabs are independent.
Blocked/full storage does not block scans and is reported when caching fails.
A hard refresh cannot reconnect to server work without a job ID; Scan History
is the existing best-effort recovery route. Backend history writes may fail, so
absence in History does not prove the scan never ran.

The old `scanApi.runScan` adapter remains compatible for other consumers. The
screener uses the new detailed adapter to avoid dropping partial-result metadata.
Sector pulse retrieval no longer extends the scan's running state and a late
pulse cannot replace one associated with a newer response.

## Verification

From `frontend/`, using the existing locked dependencies:

```sh
npm ci
npm run test:scan
npm run lint
npm run build
```

The scan tests use Node's built-in runner, TypeScript compilation and React
server rendering; no additional dependencies. They test response normalization,
state transitions, duplicate prevention, retained results, refresh recovery,
storage failures, per-user isolation, subscriptions and accessible status markup.
Run them explicitly with `npm run test:scan`; the protected CI workflow is
unchanged. These are unit/component-render tests, not
browser E2E tests. A manual browser check can run a large universe, use old tables,
navigate away/back, refresh while pending, and inspect partial/offline states.
