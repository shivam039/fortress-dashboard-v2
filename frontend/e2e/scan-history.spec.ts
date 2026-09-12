import { test, expect, loginWithFixture } from './fixtures';

test('stock and mutual-fund histories stay separate and stock replay is read-only', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  await page.getByRole('link', { name: /Scan History/ }).click();
  await expect(page.getByRole('button', { name: /Stocks/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Mutual Funds/ })).toBeVisible();
  await expect(page.getByText('Nifty 50')).toBeVisible();
  await expect(page.getByText('Direct Growth')).not.toBeVisible();

  await page.getByRole('button', { name: /Mutual Funds/ }).click();
  await expect(page).toHaveURL(/section=MF/);
  await expect(page.getByText('Direct Growth')).toBeVisible();
  await expect(page.getByText('Nifty 50')).not.toBeVisible();
  await page.reload();
  await expect(page.getByText('Direct Growth')).toBeVisible();

  await page.getByRole('button', { name: /Stocks/ }).click();
  await page.getByText('Nifty 50').click();
  await expect(page.getByRole('heading', { name: /Historical Stock Screener/ })).toBeVisible();
  await expect(page.getByText(/Read-only/)).toBeVisible();
  await expect(page.locator('pre')).toHaveCount(0);
  await expect(page.getByText(/Advanced details/)).toBeVisible();
  await page.getByRole('button', { name: /Back to Scan History/ }).click();
  await expect(page.getByRole('button', { name: /Stocks/ })).toBeVisible();
  fatalCheck();
});

test('historical context shows persisted signal and provenance without mutation', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  await page.getByRole('link', { name: /Scan History/ }).click();
  await page.getByText('Nifty 50').click();
  await expect(page.getByText('Historical Evidence Context')).toBeVisible();
  await expect(page.getByText(/score 81/)).toBeVisible();
  await expect(page.getByText(/Oracle: POSITIVE \(oracle-v1\)/)).toBeVisible();
  await expect(page.getByText(/Paper trade: linked/)).toBeVisible();
  fatalCheck();
});
