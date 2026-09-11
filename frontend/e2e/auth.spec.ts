import AxeBuilder from '@axe-core/playwright';
import { test, expect } from './fixtures';

test('login rejects invalid credentials and accepts valid credentials', async ({ page, fatalCheck }) => {
  await page.goto('/login');
  await expect(page.getByText('Fortress', { exact: false }).first()).toBeVisible();

  await page.getByLabel('Username').fill('invalid');
  await page.getByLabel('Password').fill('wrong-password');
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByText('Invalid username or password')).toBeVisible();

  await page.getByLabel('Username').fill(process.env.PLAYWRIGHT_USERNAME || 'qa_user');
  await page.getByLabel('Password').fill(process.env.PLAYWRIGHT_PASSWORD || 'fixture-only');
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole('link', { name: /Stock Screener/ }).click();
  await expect(page.getByRole('heading', { name: /Stock Screener/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: /Logout/ })).toBeVisible();
  await page.getByRole('button', { name: /Logout/ }).click();
  await expect(page.getByRole('button', { name: /Logout/ })).toHaveCount(0);
  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
  fatalCheck();
});

test('login has no serious or critical accessibility violations', async ({ page }) => {
  await page.goto('/login');
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.filter(v => ['serious', 'critical'].includes(v.impact || ''))).toEqual([]);
});
