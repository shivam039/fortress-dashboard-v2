import { test as base, expect, type Page, type Route } from '@playwright/test';

const user = {
  username: 'qa_user', full_name: 'Fortress QA', email: 'qa@example.invalid',
  phone: '', account_status: 'Active', role: 'user', last_login_at: null,
};

const history = [
  { scan_id: 101, timestamp: '2026-09-10 16:00', universe: 'Nifty 50', scan_type: 'STOCK', num_scanned: 1 },
  { scan_id: 202, timestamp: '2026-09-10 17:00', universe: 'Direct Growth', scan_type: 'MF', num_scanned: 1 },
];

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

export async function installSafeApi(page: Page): Promise<void> {
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/auth/login') {
      const data = request.postDataJSON() as { username?: string };
      return data.username === 'invalid'
        ? json(route, { detail: 'Invalid username or password' }, 401)
        : json(route, { token: 'e2e-token', username: 'qa_user', role: 'user', message: 'ok' });
    }
    if (path === '/api/auth/guest') return json(route, { token: 'e2e-token', username: 'qa_user', role: 'user', message: 'ok' });
    if (path === '/api/auth/me') return json(route, user);
    if (path === '/api/auth/logout') return json(route, { message: 'ok' });
    if (request.method() !== 'GET') return json(route, { detail: `E2E safety guard blocked ${request.method()} ${path}` }, 405);
    if (path === '/api/health') return json(route, { status: 'ok' });
    if (path === '/api/universes') return json(route, ['Nifty 50', 'Nifty Next 50', 'Nifty Midcap 100', 'Nifty Smallcap 250']);
    if (path === '/api/history/timestamps') return json(route, history);
    if (path === '/api/history/data') {
      return json(route, url.searchParams.get('scan_id') === '101'
        ? [{ Symbol: 'SAFE', Strategy: 'Long-Term Pick', Quality_Gate_Pass: true, Fortress_Score: 81 }]
        : [{ Scheme: 'QA Mutual Fund', conviction_score_v2: 72 }]);
    }
    if (path === '/api/history/context') {
      return json(route, { signals: [{ id: 501, symbol: 'SAFE', score: 81, generated_at: '2026-09-10 16:00' }], paper_trades: [{ trade_id: 7, signal_id: 501, source_type: 'ORACLE_SIGNAL', oracle_decision: 'POSITIVE', oracle_version: 'oracle-v1' }] });
    }
    if (path === '/api/orders/stats') return json(route, { total: 0, executed: 0, pending: 0, rejected: 0, cancelled: 0 });
    if (path === '/api/picks/summary') return json(route, { total: 0, hits: 0, misses: 0, expired: 0, trailing: 0, hit_rate: 0, avg_pnl: 0, avg_days: 0, best_pnl: 0, worst_pnl: 0 });
    if (path === '/api/paper-trades/metrics') return json(route, { trade_count: 0, total_gross_pnl: 0, total_net_pnl: 0, win_rate_pct: null, avg_win: null, avg_loss: null, expectancy: null, max_drawdown: 0, total_exposure: 0, turnover: 0, portfolio_return_pct: null, benchmark_excess_return_pct: null });
    if (path === '/api/options/expiries') return json(route, ['2026-09-24']);
    if (path === '/api/options/chain') return json(route, { symbol: 'NIFTY', expiry: '2026-09-24', spot: 25000, chain: [], strategies: [] });
    if (path === '/api/research-evidence') return json(route, { available: false, reason: 'insufficient evidence' });
    return json(route, []);
  });
}

// globals.css @imports Google Fonts at runtime — a real external network
// dependency of the app, not app/test noise. Allowlisted alongside the
// favicon so a transient DNS/CDN hiccup for a non-critical web font never
// flaps an otherwise-passing deterministic test; the app's own font
// fallback stack still renders correctly if this fails in production.
const IGNORABLE_RESOURCE = /favicon\.ico|fonts\.(?:googleapis|gstatic)\.com/;

// The browser's generic "Failed to load resource: ..." console message
// never includes the failing URL, so it can't be matched against
// IGNORABLE_RESOURCE here — but every such failure also fires
// `requestfailed`/`response` below (with the real URL/status, properly
// filtered — e.g. a deliberately-mocked 401 in the invalid-credentials
// test is expected behavior, not a fatal error), so dropping this URL-less
// duplicate from console loses no real coverage.
const GENERIC_NETWORK_FAILURE = /^Failed to load resource: (net::|the server responded with a status of \d+)/;
const expectedHttpFailures = new WeakMap<Page, RegExp[]>();

export function allowExpectedHttpFailure(page: Page, pattern: RegExp): void {
  expectedHttpFailures.set(page, [...(expectedHttpFailures.get(page) || []), pattern]);
}

export function watchForFatalErrors(page: Page): () => void {
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    if (IGNORABLE_RESOURCE.test(message.text()) || GENERIC_NETWORK_FAILURE.test(message.text())) return;
    failures.push(`console: ${message.text()}`);
  });
  page.on('response', response => {
    const status = response.status();
    const expected = (expectedHttpFailures.get(page) || []).some((pattern) => pattern.test(response.url()));
    if (!expected && (status >= 500 || (status === 404 && new URL(response.url()).origin === new URL(page.url() || 'http://localhost').origin))) {
      failures.push(`HTTP ${status}: ${response.url()}`);
    }
  });
  page.on('requestfailed', request => {
    if (!request.failure()?.errorText.includes('ERR_ABORTED') && !IGNORABLE_RESOURCE.test(request.url())) {
      failures.push(`request failed: ${request.url()}`);
    }
  });
  return () => expect(failures, failures.join('\n')).toEqual([]);
}

export async function loginWithFixture(page: Page): Promise<void> {
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Guest/ }).click();
  await page.getByRole('button', { name: /Continue as Guest/ }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

export const test = base.extend<{ fatalCheck: () => void }>({
  page: async ({ page }, use) => {
    await installSafeApi(page);
    // Playwright's fixture callback is named `use`; it is not a React hook.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    await use(page);
  },
  fatalCheck: async ({ page }, use) => {
    const check = watchForFatalErrors(page);
    // eslint-disable-next-line react-hooks/rules-of-hooks
    await use(check);
    check();
  },
});
export { expect };
