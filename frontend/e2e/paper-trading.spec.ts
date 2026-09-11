import { test, expect, loginWithFixture } from './fixtures';

test('paper trading is a read-only empty-state smoke path', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  await page.getByRole('link', { name: /Paper Trading/ }).click();
  await expect(page.getByText('PAPER TRADE', { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/Open PAPER Positions/)).toBeVisible();
  await expect(page.getByText(/Closed PAPER Trades/)).toBeVisible();
  await expect(page.getByText('No open paper positions.')).toBeVisible();
  await expect(page.getByText('Closed Trades')).toBeVisible();
  fatalCheck();
});
