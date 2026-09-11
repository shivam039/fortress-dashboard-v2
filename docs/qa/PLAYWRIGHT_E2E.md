# Fortress Playwright E2E

The suite has two deliberately separate modes: deterministic local/CI tests
with read-only API fixtures, and a deployed integration smoke that reads from a
configured Fortress deployment. Both modes use Chromium. A small Pixel 7 pass
covers responsive navigation and the most important read journeys.

## Local setup

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

When `PLAYWRIGHT_BASE_URL` is unset, Playwright starts Next.js at
`http://127.0.0.1:3000`. The deterministic tests intercept API calls, provide
stable history/paper-trading fixtures, and reject every non-authentication
write. They never run a scan, refresh market data, create an order, or create or
close a paper position.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `PLAYWRIGHT_BASE_URL` | Deployed frontend origin; also disables the local web server. |
| `PLAYWRIGHT_USERNAME` | Dedicated automation account username. |
| `PLAYWRIGHT_PASSWORD` | Dedicated automation account password. |

Credentials belong in local environment variables or CI secrets and must not
be committed. URLs and credentials are required for deployed smoke; missing
values cause it to skip rather than guess an environment.

## Deployed read-only smoke

```bash
PLAYWRIGHT_BASE_URL=https://fortress.example \
PLAYWRIGHT_USERNAME=qa-readonly \
PLAYWRIGHT_PASSWORD='from-a-secret-store' \
npm run test:e2e:smoke
```

The deployed project permits authentication plus GET/HEAD requests only. It
blocks all other Fortress API writes in the browser before they reach the
server. It verifies login, dashboard, stock screener, Scan History, and Paper
Trading rendering. It must never click scan/refresh/backfill, evidence creation,
order, or paper-position controls.

## Failures and accessibility

Every suite records uncaught page errors, important console errors, request
failures, API 5xx responses, and same-origin 404s. The allowlist contains only
aborted browser requests and a missing favicon. Axe checks login, dashboard,
stock screener, Scan History, and Paper Trading; only serious and critical
violations fail initially, while the HTML report retains all details.

Artifacts are written to `frontend/test-results/`; the HTML report is
`frontend/playwright-report/`. Open a trace with
`npx playwright show-trace test-results/<test>/trace.zip`, or the report with
`npx playwright show-report`. Screenshots, videos, traces, and reports may
contain rendered account data, so use a dedicated least-privilege account and
restrict artifact access.

## Known exclusions

- No mutating E1/E2/E3/O1, broker, order, scan, refresh, or backfill journey.
- No assertion on volatile prices, scores, evidence availability, or history
  volume.
- Evidence is exercised only where the existing UI renders it; Fortress has no
  first-class Evidence navigation route today.
- Firefox/WebKit and pixel-perfect visual comparisons are intentionally out of
  scope.
