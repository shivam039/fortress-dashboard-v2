import { test, expect, loginWithFixture } from './fixtures';

test('mobile navigation, history detail, and paper trading remain usable', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  const openMenu = page.getByRole('button', { name: /Open menu/ });
  await expect(openMenu).toBeVisible();

  await openMenu.click();
  await expect(page.getByRole('navigation')).toBeInViewport();
  await page.getByRole('link', { name: /Scan History/ }).click();
  await page.getByRole('button', { name: /Stocks/ }).click();
  await page.getByText('Nifty 50').click();
  await expect(page.getByRole('heading', { name: /Historical Stock Screener/ })).toBeVisible();
  await page.getByRole('button', { name: /Back to Scan History/ }).click();

  await page.getByRole('button', { name: /Open menu/ }).click();
  await page.getByRole('link', { name: /Paper Trading/ }).click();
  await expect(page.getByText(/Open PAPER Positions/)).toBeVisible();

  const dimensions = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport + 40);
  fatalCheck();
});
