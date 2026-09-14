import { test, expect, loginWithFixture } from './fixtures';

test('tour remains usable when sidebar targets are hidden on mobile', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  await page.getByRole('button', { name: 'Help and product tour' }).click();
  await page.getByRole('button', { name: 'Take a Tour' }).click();

  const dialog = page.getByRole('dialog', { name: 'Fortress product tour' });
  await expect(dialog).toBeInViewport();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Find and inspect stock signals')).toBeVisible();
  await page.getByRole('button', { name: 'Skip tour' }).click();
  await expect(dialog).toBeHidden();

  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport + 40);
  fatalCheck();
});
