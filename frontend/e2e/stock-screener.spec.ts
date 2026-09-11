import { test, expect, loginWithFixture } from './fixtures';

test('stock screener exposes four universes and safe search without starting a scan', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  await page.getByRole('link', { name: /Stock Screener/ }).click();
  const universe = page.locator('select').first();
  await expect(universe.locator('option')).toHaveCount(4);
  await universe.selectOption({ label: 'Nifty Next 50' });
  await expect(universe).toHaveValue('Nifty Next 50');
  await expect(page.getByRole('button', { name: /Run Screener/ })).toBeVisible();
  await expect(page.locator('input')).not.toHaveCount(0);
  fatalCheck();
});
