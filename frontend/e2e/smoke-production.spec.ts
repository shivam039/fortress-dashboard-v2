import { test, expect } from '@playwright/test';
import { watchForFatalErrors } from './fixtures';

test('deployed Fortress supports authenticated read-only journeys', async ({ page }) => {
  const username = process.env.PLAYWRIGHT_USERNAME;
  const password = process.env.PLAYWRIGHT_PASSWORD;
  test.skip(!process.env.PLAYWRIGHT_BASE_URL, 'PLAYWRIGHT_BASE_URL is required for deployed smoke');
  test.skip(!username || !password, 'deployed smoke credentials are required');
  const checkErrors = watchForFatalErrors(page);

  await page.route('**/api/**', async route => {
    const request = route.request();
    const authPath = new URL(request.url()).pathname;
    const authMutation = ['/api/auth/login', '/api/auth/logout'].includes(authPath);
    if (!['GET', 'HEAD'].includes(request.method()) && !authMutation) {
      await route.abort('blockedbyclient');
      throw new Error(`Production safety guard blocked ${request.method()} ${authPath}`);
    }
    await route.continue();
  });

  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Username').fill(username!);
  await page.getByLabel('Password').fill(password!);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  for (const [label, heading] of [
    ['Stock Screener', /Stock Screener/],
    ['Scan History', /Scan History/],
    ['Paper Trading', /Paper Trading/],
  ] as const) {
    await page.getByRole('link', { name: new RegExp(label) }).click();
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
  }
  await expect(page.getByText('PAPER TRADE', { exact: false }).first()).toBeVisible();
  checkErrors();
});
