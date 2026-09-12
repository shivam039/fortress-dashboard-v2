import { test, expect } from './fixtures';

test('API 500 is surfaced without a fatal page or stale success state', async ({ page }) => {
  await page.route('**/api/auth/guest', route => route.fulfill({
    status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'simulated failure' }),
  }));
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Guest/ }).click();
  await page.getByRole('button', { name: /Continue as Guest/ }).click();
  await expect(page.locator('body')).not.toContainText(/Unhandled Runtime Error|Application error/i);
});

test('401 login failure remains visible and does not redirect', async ({ page }) => {
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Username').fill('invalid');
  await page.getByLabel('Password').fill('invalid');
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByText('Invalid username or password')).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});
